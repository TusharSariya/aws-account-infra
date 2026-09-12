moved {
  from = aws_rolesanywhere_trust_anchor.backup
  to   = aws_rolesanywhere_trust_anchor.backup[0]
}

moved {
  from = aws_iam_role.upload
  to   = aws_iam_role.upload[0]
}

moved {
  from = aws_iam_role_policy_attachment.upload
  to   = aws_iam_role_policy_attachment.upload[0]
}

moved {
  from = aws_rolesanywhere_profile.backup
  to   = aws_rolesanywhere_profile.backup[0]
}
