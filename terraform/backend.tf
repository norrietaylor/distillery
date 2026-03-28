terraform {
  backend "s3" {
    bucket         = "distillery-terraform-state"
    key            = "production/terraform.tfstate"
    region         = "us-east-1"
    dynamodb_table = "distillery-terraform-lock"
    encrypt        = true
  }
}
