locals {
  bookings_path = "${path.module}/../../../../../apps/ecr/court-booker/bookings.yaml"
  bookings      = yamldecode(file(local.bookings_path))

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
    if try(rule.enabled, false) && var.booker_image_tag != ""
  }

  # One-shot `at()` schedules. Run on Playwright only while the API zip is not
  # retargeted, so both stacks cannot fire the same booking.
  oneshot = {
    for rule in try(local.bookings.oneshot, []) :
    rule.name => {
      activity     = rule.activity
      date         = tostring(rule.date)
      time         = tostring(rule.time)
      invoke_at    = tostring(rule.invoke_at)
      duration_min = try(tonumber(rule.duration_min), 60)
      people       = try(tonumber(rule.people), 1)
    }
    if try(rule.enabled, false) && var.booker_image_tag != "" && var.booker_api_zip_key == ""
  }
}
