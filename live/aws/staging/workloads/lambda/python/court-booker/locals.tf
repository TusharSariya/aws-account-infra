locals {
  bookings_path = "${path.module}/../../../../../../../apps/ecr/court-booker/bookings.yaml"
  bookings      = yamldecode(file(local.bookings_path))
  zip_ready     = startswith(var.booker_api_zip_key, "stable/")
  horizon_hours = tonumber(try(local.bookings.horizon_hours, 72))

  weekday_unlock = {
    Mon = "FRI"
    Tue = "SAT"
    Wed = "SUN"
    Thu = "MON"
    Fri = "TUE"
    Sat = "WED"
    Sun = "THU"
  }

  weekly_cron = {
    for rule in local.bookings.weekly :
    format("%s-%s-%s", rule.activity, rule.weekday, replace(tostring(rule.time), ":", "")) => {
      activity     = rule.activity
      weekday      = rule.weekday
      time         = tostring(rule.time)
      duration_min = try(tonumber(rule.duration_min), 60)
      people       = try(tonumber(rule.people), 1)
      cron_hour    = tonumber(split(":", tostring(rule.time))[0])
      cron_minute  = tonumber(split(":", tostring(rule.time))[1])
      cron_dow     = local.weekday_unlock[rule.weekday]
    }
    if try(rule.enabled, false) && local.zip_ready
  }

  # YAML date/time is the court slot. EventBridge `at()` is that instant minus horizon_hours.
  # Treat wall-clock as UTC so formatdate keeps the same HH:MM for America/St_Johns.
  oneshot = {
    for rule in try(local.bookings.oneshot, []) :
    rule.name => {
      activity = rule.activity
      date     = tostring(rule.date)
      time     = tostring(rule.time)
      invoke_at = formatdate(
        "YYYY-MM-DD'T'HH:mm:ss",
        timeadd("${rule.date}T${rule.time}:00Z", "-${local.horizon_hours}h")
      )
      duration_min = try(tonumber(rule.duration_min), 60)
      people       = try(tonumber(rule.people), 1)
    }
    if try(rule.enabled, false) && local.zip_ready
  }
}
