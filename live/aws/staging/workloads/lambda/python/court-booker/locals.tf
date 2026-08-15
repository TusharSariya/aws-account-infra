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

  oneshot_input = {
    for rule in try(local.bookings.oneshot, []) :
    rule.name => {
      activity     = rule.activity
      duration_min = try(tonumber(rule.duration_min), 60)
      people       = try(tonumber(rule.people), 1)
      booking_date = try(tostring(rule.booking_date), try(tostring(rule.date), ""))
      booking_time = try(tostring(rule.booking_time), try(tostring(rule.time), ""))
      invoke_at    = try(tostring(rule.invoke_at), "")
      enabled      = try(rule.enabled, false)
    }
  }

  # booking_* is the court slot; invoke_at is EventBridge. Whichever is omitted
  # is filled with a horizon_hours offset. Set both to decouple them.
  oneshot = {
    for name, rule in local.oneshot_input :
    name => {
      activity     = rule.activity
      duration_min = rule.duration_min
      people       = rule.people
      date = (
        rule.booking_date != "" ? rule.booking_date :
        formatdate("YYYY-MM-DD", timeadd("${rule.invoke_at}Z", "${local.horizon_hours}h"))
      )
      time = (
        rule.booking_time != "" ? rule.booking_time :
        formatdate("HH:mm", timeadd("${rule.invoke_at}Z", "${local.horizon_hours}h"))
      )
      invoke_at = (
        rule.invoke_at != "" ? rule.invoke_at : formatdate(
          "YYYY-MM-DD'T'HH:mm:ss",
          timeadd("${rule.booking_date}T${rule.booking_time}:00Z", "-${local.horizon_hours}h")
        )
      )
    }
    if rule.enabled && local.zip_ready && (
      rule.invoke_at != "" || (rule.booking_date != "" && rule.booking_time != "")
    )
  }
}
