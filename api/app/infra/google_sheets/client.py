from __future__ import annotations
from typing import Any, List, Optional, Dict
from collections.abc import Iterable, Sequence
import json
import asyncio

from google.oauth2.service_account import Credentials
from gspread_asyncio import AsyncioGspreadClientManager, AsyncioGspreadSpreadsheet, AsyncioGspreadWorksheet


_DEFAULT_SCOPES = [
	"https://www.googleapis.com/auth/spreadsheets",
	"https://www.googleapis.com/auth/drive"
]


class AsyncGoogleSheets:
	def __init__(
		self,
		service_account_file: Optional[str] = None,
		service_account_info: Optional[Dict[str, Any]] = None,
		scopes: Optional[Sequence[str]] = None
	) -> None:
		if not service_account_file and not service_account_info:
			raise ValueError("Нужно передать service_account_file или service_account_info")

		self._scopes = list(scopes) if scopes else list(_DEFAULT_SCOPES)

		def _make_creds() -> Credentials:
			if service_account_info:
				return Credentials.from_service_account_info(service_account_info, scopes=self._scopes)
			return Credentials.from_service_account_file(service_account_file, scopes=self._scopes)  # type: ignore[arg-type]

		self._manager = AsyncioGspreadClientManager(_make_creds)

	async def _client(self):
		return await self._manager.authorize()

	async def _open_spreadsheet(self, *, key: Optional[str] = None, url: Optional[str] = None, title: Optional[str] = None) -> AsyncioGspreadSpreadsheet:
		client = await self._client()
		if key:
			return await client.open_by_key(key)
		if url:
			return await client.open_by_url(url)
		if title:
			return await client.open(title)
		raise ValueError("Нужно указать один из параметров: key | url | title")

	async def create_spreadsheet(
		self,
		title: str,
		folder_id: Optional[str] = None,
		locale: str = "en_US",
		timezone: str = "UTC",
		share_to: Optional[str] = None,
		role: str = "writer",
		perm_type: str = "user",
		notify: bool = True
	) -> AsyncioGspreadSpreadsheet:

		client = await self._client()
		ss = await client.create(title=title, folder_id=folder_id)
		await ss.batch_update({
			"properties": {
				"title": title,
				"locale": locale,
				"timeZone": timezone
			}
		})
		if share_to:
			await ss.share(share_to, perm_type=perm_type, role=role, notify=notify)
		return ss

	async def open_by_key(self, key: str) -> AsyncioGspreadSpreadsheet:
		return await self._open_spreadsheet(key=key)

	async def open_by_url(self, url: str) -> AsyncioGspreadSpreadsheet:
		return await self._open_spreadsheet(url=url)

	async def open_by_title(self, title: str) -> AsyncioGspreadSpreadsheet:
		return await self._open_spreadsheet(title=title)

	async def share(
		self,
		key: str,
		email: str,
		role: str = "writer",
		perm_type: str = "user",
		notify: bool = True
	) -> None:
		ss = await self.open_by_key(key)
		await ss.share(email, perm_type=perm_type, role=role, notify=notify)

	async def list_worksheets(self, key: str) -> List[str]:
		ss = await self.open_by_key(key)
		ws = await ss.worksheets()
		return [w.title for w in ws]

	async def batch_update(self, key: str, requests_body: Dict[str, Any]) -> Dict[str, Any]:
		ss = await self.open_by_key(key)
		return await ss.batch_update(requests_body)

	async def add_worksheet(self, key: str, title: str, rows: int = 100, cols: int = 26) -> AsyncioGspreadWorksheet:
		ss = await self.open_by_key(key)
		return await ss.add_worksheet(title=title, rows=rows, cols=cols)

	async def delete_worksheet(self, key: str, title: str) -> None:
		ss = await self.open_by_key(key)
		ws = await ss.worksheet(title)
		await ss.del_worksheet(ws)

	async def resize_worksheet(self, key: str, title: str, rows: Optional[int] = None, cols: Optional[int] = None) -> None:
		ss = await self.open_by_key(key)
		ws = await ss.worksheet(title)
		if rows is not None:
			await ws.resize(rows=rows)
		if cols is not None:
			await ss.batch_update({
				"requests": [{
					"updateSheetProperties": {
						"properties": {
							"sheetId": ws.id,
							"gridProperties": {"columnCount": cols}
						},
						"fields": "gridProperties.columnCount"
					}
				}]
			})

	async def get_values(self, key: str, a1_range: str) -> List[List[Any]]:
		ss = await self.open_by_key(key)
		resp = await ss.values_get(a1_range)
		return resp.get("values", [])

	async def set_values(
		self,
		key: str,
		a1_range: str,
		values: Sequence[Sequence[Any]],
		value_input_option: str = "USER_ENTERED"
	) -> Dict[str, Any]:
		ss = await self.open_by_key(key)
		return await ss.values_update(a1_range, params={"valueInputOption": value_input_option}, body={"values": values})  # type: ignore[attr-defined]

	async def append_rows(
		self,
		key: str,
		sheet_title: str,
		rows: Sequence[Sequence[Any]],
		value_input_option: str = "USER_ENTERED"
	) -> Dict[str, Any]:
		ss = await self.open_by_key(key)
		ws = await ss.worksheet(sheet_title)
		return await ws.append_rows(rows, value_input_option=value_input_option)

	async def clear_range(self, key: str, a1_range: str) -> None:
		ss = await self.open_by_key(key)
		await ss.values_clear(a1_range)

	async def find_first(self, key: str, sheet_title: str, query: str, in_formula: bool = False):
		ss = await self.open_by_key(key)
		ws = await ss.worksheet(sheet_title)
		return await ws.find(query, in_formula=in_formula)

	async def findall(self, key: str, sheet_title: str, query: str, in_formula: bool = False):
		ss = await self.open_by_key(key)
		ws = await ss.worksheet(sheet_title)
		return await ws.findall(query, in_formula=in_formula)

	async def ensure_worksheet(self, key: str, title: str, rows: int = 100, cols: int = 26) -> AsyncioGspreadWorksheet:
		ss = await self.open_by_key(key)
		try:
			return await ss.worksheet(title)
		except Exception:
			return await ss.add_worksheet(title=title, rows=rows, cols=cols)

	async def format_range(self, key: str, sheet_title: str, a1_range: str, user_entered_format: Dict[str, Any]) -> None:
		ss = await self.open_by_key(key)
		ws = await ss.worksheet(sheet_title)
		await ss.batch_update({
			"requests": [{
				"repeatCell": {
					"range": {
						"sheetId": ws.id,
						"startRowIndex": None,
						"startColumnIndex": None
					},
					"cell": {"userEnteredFormat": user_entered_format},
					"fields": "userEnteredFormat"
				}
			}],
			"includeSpreadsheetInResponse": False
		})

	async def get_worksheet_values(
		self,
		key: str,
		sheet_title: str
	) -> List[List[Any]]:
		ss = await self.open_by_key(key)
		ws = await ss.worksheet(sheet_title)
		return await ws.get_all_values()

	def get_values_sync(self, key, a1_range):
		return asyncio.run(self.get_values(key, a1_range))
