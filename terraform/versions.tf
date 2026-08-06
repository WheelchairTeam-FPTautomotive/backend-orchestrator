terraform {
  required_version = ">= 1.5"

  backend "local" {}

  required_providers {
    aws = {
      source = "hashicorp/aws"
      # inference_ami_version on SageMaker endpoint config needs >= 5.56
      version = ">= 5.56, < 6.0"
    }
  }
}
