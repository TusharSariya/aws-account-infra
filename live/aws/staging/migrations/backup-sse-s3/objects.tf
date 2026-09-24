# Completed 2026-09-24. Backup contents remain owned by their writers.
# Forget only: removing migration bookkeeping must never delete copied versions.
removed {
  from = aws_s3_object_copy.reencrypted
  lifecycle { destroy = false }
}
