# Backend bucket and table names must match the bootstrap output.
# See terraform/bootstrap/main.tf — defaults: bucket_name="distillery-terraform-state",
# lock_table_name="distillery-terraform-lock".
terraform {
  backend "s3" {
    bucket         = "distillery-terraform-state"
    key            = "production/terraform.tfstate"
    region         = "us-east-1"
    dynamodb_table = "distillery-terraform-lock"
    encrypt        = true
  }
}
