# Imported orphaned staging NAT IP allocations, then retired on 2026-09-24.
# Their original local states were replaced by LocalStack fixtures.
removed {
  from = aws_eip.ohio
  lifecycle { destroy = true }
}
removed {
  from = aws_eip.california
  lifecycle { destroy = true }
}
