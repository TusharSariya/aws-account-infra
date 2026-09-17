aws_account_id             = "992382747916"
region                     = "us-east-1"
aws_profile                = "admin"
terraform_deploy_role_name = "TerraformDeploy"
default_tags               = { managed_by = "opentofu", repo = "aws-account-infra" }

# Increment when replacing a compromised/lost uploader identity.
backup_certificate_common_name = "homelab-backup-uploader-01"

# Start with manual encrypted uploads using the existing AWS administrator login.
create_backup_identity = false

# Public CA only. Private signing material remains outside Kubernetes and Git.
postgres_ca_certificate_pem = <<-PEM
-----BEGIN CERTIFICATE-----
MIIFPjCCAyagAwIBAgIUI489x/CV2iPbc5ZQjXf9pGNjQDYwDQYJKoZIhvcNAQEL
BQAwJTEjMCEGA1UEAwwaaG9tZWxhYi1wb3N0Z3Jlcy1iYWNrdXAtY2EwHhcNMjYw
OTE3MTYyODI2WhcNMzYwOTE0MTYyODI2WjAlMSMwIQYDVQQDDBpob21lbGFiLXBv
c3RncmVzLWJhY2t1cC1jYTCCAiIwDQYJKoZIhvcNAQEBBQADggIPADCCAgoCggIB
AOuVX7hTzRgPqMVe47RLbvxPqBJ0VCsib9tR3bY8EcEbtKdfvIM7U+NlJY2opYmV
3aFHRdbeHvY11Dc6eYk/rsEfL0aq2Jc6P3C1mlfmnyk2Zh1NYK4GrT5MA8sTwmXY
imR7PexZtrhlgT0GyRXuVWYQ80Fz7j847TKLjxxL2azCmhKHtSrtFG0NI8lw0knQ
QyJmO3AdGZQEQvQWd/+f4X1Q+W+Ki9hvNO5Y/SDcfnt+dYtLcrcwybouhDNTySmw
rdllh5tiatEmeHZwalrNzi0u1w/w/QH+KyATxNeX/JN5bko+eAR1aOKRAtnuNIA/
daAZ3L3PqBEuFaMU8klbJlZguJBuZje4ddwHEqsVlYLZrbMOfkwO+2/mnJi8Z2UV
fD3LZgr2CGTUNpUZmjg0xAzpVzQVLZEEACGfRsuHyM9eku/p94vx4CtkW118OPrz
fIp9spq8p4Q3cOIsZ+anZHnaUgHpu/W1HQx1Mu5ztSfbdk3CAVIP2C6AV1y8O8fY
X2fC4NLHMEKcie2sLJhXbxClr/EpAPrnWQ30BH0QpZPmSYzhLiXhphL7ZdYJsMp3
FbQK4sWxIZSLkpsXYhNfvK+NvThJZGyN9YTCTcdyYKZc+66CbvM5H3BoEAHPpxbY
KrTTeMdOuJd1PVb7p+t6+zCG2yRJguq/nt35QuGB4b4lAgMBAAGjZjBkMBIGA1Ud
EwEB/wQIMAYBAf8CAQAwDgYDVR0PAQH/BAQDAgEGMB0GA1UdDgQWBBQEZcVR56CT
0lxhr7i6SjGx8P8oLDAfBgNVHSMEGDAWgBQEZcVR56CT0lxhr7i6SjGx8P8oLDAN
BgkqhkiG9w0BAQsFAAOCAgEAK0eevG7YIy5MgZht7ucmCpb0sQkrgZYMvoogcBHL
8YfynhPH1sZGHLzrYtOLUhbIcBcZGb91pZqjSXuySoPFYCiR9tD/bcindqYpzTsU
FMwLq09aqQSVUsjJc6V67OnH/oNowmFB1QEpAwdGmDgVNGpDnc79HMrvfbPxyGzS
IRJ9yDY/PQxrHXwZWd4MtUPESA4eBHFpQFYSq8aik1jrcw0hYDPvRIPVH8RDkAyE
/aKOFFT2CNSJInjMIFrFd6+pJ1NkjNEXm77rJFd3Xvb8kXiYgc6Wo7HH3QuYd5FE
AulG4jMHKaoUFHLL6NifS36Iej3gWmaYdp/Ir1E4CraLyDrIMmSITa0MgzF9ZcPG
2uuh7P7sX+EiuUwHVuLGtxnmwKRGSg7xJLJ+ydZozI667YRyv3i9OZ59CppModzb
jf41S0aKP0tCrfnuai5cUmUJKLOwVGs5xJobEscCSbOpyEUbg0IUEfbDF0VT1jI4
8Ed/GCIJww0vwzDfdiar9CExbX8iZmUK8GTJbrfTt/i7R25Z0R+15LafEpsuze6F
otnZzm/5Ggy0IbiWp2UP6/AshZcwVHvccPPwISwp0tAqkVJCI0OW0EU0zzTCxkga
YCOII+LPHCkmKx8guPeKltyORWJ0ICg8dXCEjuHxDLp3YDVPZyGaNqfshRUU+PNc
m64=
-----END CERTIFICATE-----
PEM
