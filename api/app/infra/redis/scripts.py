ENQUEUE_SCRIPT = """
local has_idempotency = ARGV[5]
if has_idempotency == "1" then
  local existing_task_id = redis.call("GET", KEYS[3])
  if existing_task_id then
    return {"existing", existing_task_id}
  end
end

if redis.call("EXISTS", KEYS[1]) == 1 then
  return {"existing", ARGV[1]}
end

for i = 7, #ARGV, 2 do
  redis.call("HSET", KEYS[1], ARGV[i], ARGV[i + 1])
end

redis.call("ZADD", KEYS[2], ARGV[3], ARGV[1])
redis.call("ZADD", KEYS[4], ARGV[4], ARGV[1])
redis.call("ZADD", KEYS[5], ARGV[4], ARGV[1])

if has_idempotency == "1" then
  local was_set = redis.call("SET", KEYS[3], ARGV[1], "EX", ARGV[6], "NX")
  if not was_set then
    local existing_task_id = redis.call("GET", KEYS[3])
    if existing_task_id then
      redis.call("DEL", KEYS[1])
      redis.call("ZREM", KEYS[2], ARGV[1])
      redis.call("ZREM", KEYS[4], ARGV[1])
      redis.call("ZREM", KEYS[5], ARGV[1])
      return {"existing", existing_task_id}
    end
  end
end

return {"created", ARGV[1]}
"""


CLAIM_SCRIPT = """
local ids = redis.call("ZRANGEBYSCORE", KEYS[1], "-inf", ARGV[1], "LIMIT", 0, ARGV[2])
local claimed = {}

for _, task_id in ipairs(ids) do
  local task_key = ARGV[8] .. ":task:" .. task_id
  local status = redis.call("HGET", task_key, "status")

  if status == "queued" or status == "scheduled" or status == "retrying" then
    redis.call("ZREM", KEYS[1], task_id)
    redis.call("ZREM", ARGV[8] .. ":index:status:" .. status, task_id)
    redis.call("ZADD", KEYS[2], ARGV[4], task_id)
    redis.call("ZADD", KEYS[3], ARGV[3], task_id)
    redis.call(
      "HSET",
      task_key,
      "status", "running",
      "attempts", redis.call("HINCRBY", task_key, "attempts", 1),
      "lock_owner", ARGV[5],
      "lease_expires_at", ARGV[6],
      "lease_expires_at_ms", ARGV[4],
      "updated_at", ARGV[7],
      "claimed_at", ARGV[7]
    )
    table.insert(claimed, task_id)
  else
    redis.call("ZREM", KEYS[1], task_id)
  end
end

return claimed
"""


HEARTBEAT_SCRIPT = """
if redis.call("EXISTS", KEYS[1]) == 0 then
  return {"missing", ""}
end

local status = redis.call("HGET", KEYS[1], "status")
if status ~= "running" then
  return {"conflict", status or ""}
end

local owner = redis.call("HGET", KEYS[1], "lock_owner")
if ARGV[2] ~= "" and owner ~= ARGV[2] then
  return {"owner_mismatch", owner or ""}
end

redis.call("ZADD", KEYS[2], ARGV[4], ARGV[1])
redis.call(
  "HSET",
  KEYS[1],
  "lease_expires_at", ARGV[3],
  "lease_expires_at_ms", ARGV[4],
  "updated_at", ARGV[5]
)
return {"ok", "running"}
"""


COMPLETE_SCRIPT = """
if redis.call("EXISTS", KEYS[1]) == 0 then
  return {"missing", ""}
end

local status = redis.call("HGET", KEYS[1], "status")
if status ~= "running" then
  return {"conflict", status or ""}
end

local owner = redis.call("HGET", KEYS[1], "lock_owner")
if ARGV[2] ~= "" and owner ~= ARGV[2] then
  return {"owner_mismatch", owner or ""}
end

redis.call("ZREM", KEYS[2], ARGV[1])
redis.call("ZREM", KEYS[3], ARGV[1])
redis.call("ZADD", KEYS[4], ARGV[4], ARGV[1])
redis.call(
  "HSET",
  KEYS[1],
  "status", "succeeded",
  "result", ARGV[5],
  "lock_owner", "",
  "lease_expires_at", "",
  "lease_expires_at_ms", "",
  "updated_at", ARGV[3],
  "finished_at", ARGV[3]
)
return {"ok", "succeeded"}
"""


FAIL_SCRIPT = """
if redis.call("EXISTS", KEYS[1]) == 0 then
  return {"missing", ""}
end

local status = redis.call("HGET", KEYS[1], "status")
if status ~= "running" then
  return {"conflict", status or ""}
end

local owner = redis.call("HGET", KEYS[1], "lock_owner")
if ARGV[2] ~= "" and owner ~= ARGV[2] then
  return {"owner_mismatch", owner or ""}
end

local attempts = tonumber(redis.call("HGET", KEYS[1], "attempts") or "0")
local max_attempts = tonumber(redis.call("HGET", KEYS[1], "max_attempts") or "1")
local should_retry = ARGV[6] == "1" and attempts < max_attempts

redis.call("ZREM", KEYS[2], ARGV[1])
redis.call("ZREM", KEYS[3], ARGV[1])

if should_retry then
  redis.call("ZADD", KEYS[4], ARGV[8], ARGV[1])
  redis.call("ZADD", KEYS[5], ARGV[4], ARGV[1])
  redis.call(
    "HSET",
    KEYS[1],
    "status", "retrying",
    "last_error", ARGV[5],
    "lock_owner", "",
    "lease_expires_at", "",
    "lease_expires_at_ms", "",
    "ready_at_ms", ARGV[7],
    "updated_at", ARGV[3]
  )
  return {"ok", "retrying"}
end

redis.call("ZADD", KEYS[6], ARGV[4], ARGV[1])
redis.call(
  "HSET",
  KEYS[1],
  "status", "failed",
  "last_error", ARGV[5],
  "lock_owner", "",
  "lease_expires_at", "",
  "lease_expires_at_ms", "",
  "updated_at", ARGV[3],
  "finished_at", ARGV[3]
)
return {"ok", "failed"}
"""


CANCEL_SCRIPT = """
if redis.call("EXISTS", KEYS[1]) == 0 then
  return {"missing", ""}
end

local status = redis.call("HGET", KEYS[1], "status")
if status == "running" and ARGV[2] ~= "1" then
  redis.call(
    "HSET",
    KEYS[1],
    "cancel_requested", "true",
    "cancel_reason", ARGV[5],
    "updated_at", ARGV[3]
  )
  return {"ok", "cancel_requested"}
end

redis.call("ZREM", KEYS[2], ARGV[1])
redis.call("ZREM", KEYS[3], ARGV[1])
redis.call("ZREM", ARGV[6] .. ":index:status:queued", ARGV[1])
redis.call("ZREM", ARGV[6] .. ":index:status:scheduled", ARGV[1])
redis.call("ZREM", ARGV[6] .. ":index:status:retrying", ARGV[1])
redis.call("ZREM", ARGV[6] .. ":index:status:running", ARGV[1])
redis.call("ZADD", KEYS[4], ARGV[4], ARGV[1])
redis.call(
  "HSET",
  KEYS[1],
  "status", "cancelled",
  "cancel_requested", "false",
  "cancel_reason", ARGV[5],
  "lock_owner", "",
  "lease_expires_at", "",
  "lease_expires_at_ms", "",
  "updated_at", ARGV[3],
  "finished_at", ARGV[3]
)
return {"ok", "cancelled"}
"""


RECOVER_EXPIRED_SCRIPT = """
local ids = redis.call("ZRANGEBYSCORE", KEYS[1], "-inf", ARGV[1], "LIMIT", 0, ARGV[2])
local requeued = 0
local failed = 0

for _, task_id in ipairs(ids) do
  local task_key = ARGV[8] .. ":task:" .. task_id
  local status = redis.call("HGET", task_key, "status")

  redis.call("ZREM", KEYS[1], task_id)
  redis.call("ZREM", KEYS[2], task_id)

  if status == "running" then
    local attempts = tonumber(redis.call("HGET", task_key, "attempts") or "0")
    local max_attempts = tonumber(redis.call("HGET", task_key, "max_attempts") or "1")

    if attempts < max_attempts then
      local priority = tonumber(redis.call("HGET", task_key, "priority") or "50")
      local delay_ms = tonumber(ARGV[5]) * (2 ^ math.max(attempts - 1, 0))
      delay_ms = math.min(delay_ms, tonumber(ARGV[6]))
      local ready_at_ms = tonumber(ARGV[1]) + delay_ms
      local score = (ready_at_ms * tonumber(ARGV[7])) + (100 - priority)

      redis.call("ZADD", KEYS[3], score, task_id)
      redis.call("ZADD", KEYS[4], ARGV[3], task_id)
      redis.call(
        "HSET",
        task_key,
        "status", "retrying",
        "last_error", "worker lease expired",
        "lock_owner", "",
        "lease_expires_at", "",
        "lease_expires_at_ms", "",
        "ready_at_ms", ready_at_ms,
        "updated_at", ARGV[4]
      )
      requeued = requeued + 1
    else
      redis.call("ZADD", KEYS[5], ARGV[3], task_id)
      redis.call(
        "HSET",
        task_key,
        "status", "failed",
        "last_error", "worker lease expired",
        "lock_owner", "",
        "lease_expires_at", "",
        "lease_expires_at_ms", "",
        "updated_at", ARGV[4],
        "finished_at", ARGV[4]
      )
      failed = failed + 1
    end
  end
end

return {requeued, failed}
"""
