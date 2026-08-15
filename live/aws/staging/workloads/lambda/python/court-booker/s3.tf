data "aws_s3_bucket" "zips" {
  bucket = local.zip_bucket_name
}

data "aws_s3_object" "zip" {
  count  = local.zip_ready ? 1 : 0
  bucket = data.aws_s3_bucket.zips.id
  key    = var.booker_api_zip_key
}
