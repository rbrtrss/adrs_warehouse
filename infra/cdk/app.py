#!/usr/bin/env python3
import aws_cdk as cdk
from stacks.adrs_stack import AdrsWarehouseStack

app = cdk.App()
AdrsWarehouseStack(app, "AdrsWarehouseStack")
app.synth()
