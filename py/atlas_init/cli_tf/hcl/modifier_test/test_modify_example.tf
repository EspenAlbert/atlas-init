resource "aws_s3_bucket" "bucket" {
  bucket = "bucket_id"
  force_destroy = true
  tags= {
    Name= "My bucket"
    Environment= "Dev"
  }
}
