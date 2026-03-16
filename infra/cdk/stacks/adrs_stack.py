import aws_cdk as cdk
import aws_cdk.aws_iam as iam
import aws_cdk.aws_lambda as lambda_
import aws_cdk.aws_logs as logs
import aws_cdk.aws_cloudwatch as cloudwatch
import aws_cdk.aws_cloudwatch_actions as cw_actions
import aws_cdk.aws_sns as sns
import aws_cdk.aws_sns_subscriptions as sns_subs
import aws_cdk.aws_scheduler as scheduler
from constructs import Construct


ALERT_EMAIL = "roberto@example.com"  # Update before deploy
MOTHERDUCK_DB = "adrs_warehouse"


class AdrsWarehouseStack(cdk.Stack):
    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # --- IAM Role ---
        role = iam.Role(
            self,
            "LambdaRole",
            assumed_by=iam.ServicePrincipal("lambda.amazonaws.com"),
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name(
                    "service-role/AWSLambdaBasicExecutionRole"
                )
            ],
        )

        # Allow Lambda to read the MotherDuck token from Secrets Manager
        role.add_to_policy(
            iam.PolicyStatement(
                actions=["secretsmanager:GetSecretValue"],
                resources=[
                    f"arn:aws:secretsmanager:{self.region}:{self.account}"
                    ":secret:adrs-warehouse/motherduck-token*"
                ],
            )
        )

        # --- CloudWatch Log Group ---
        log_group = logs.LogGroup(
            self,
            "LambdaLogGroup",
            log_group_name="/aws/lambda/adrs-warehouse-update",
            retention=logs.RetentionDays.ONE_MONTH,
            removal_policy=cdk.RemovalPolicy.DESTROY,
        )

        # --- Lambda ---
        fn = lambda_.Function(
            self,
            "UpdateFunction",
            function_name="adrs-warehouse-update",
            runtime=lambda_.Runtime.PYTHON_3_12,
            handler="lambda_handler.handler",
            code=lambda_.Code.from_asset("../lambda"),
            memory_size=512,
            timeout=cdk.Duration.seconds(300),
            role=role,
            reserved_concurrent_executions=1,
            log_group=log_group,
            environment={
                "MOTHERDUCK_DB": MOTHERDUCK_DB,
            },
        )

        # Inject MotherDuck token at runtime via Secrets Manager
        lambda_.CfnFunction(self, "TokenSecret")  # placeholder comment
        secret_arn = (
            f"arn:aws:secretsmanager:{self.region}:{self.account}"
            ":secret:adrs-warehouse/motherduck-token"
        )
        cfn_fn = fn.node.default_child
        cfn_fn.add_property_override(
            "Environment.Variables.MOTHERDUCK_TOKEN",
            {
                "Fn::Sub": (
                    "{{resolve:secretsmanager:"
                    f"{secret_arn}"
                    ":SecretString:MOTHERDUCK_TOKEN}}"
                )
            },
        )

        # --- EventBridge Scheduler Role ---
        scheduler_role = iam.Role(
            self,
            "SchedulerRole",
            assumed_by=iam.ServicePrincipal("scheduler.amazonaws.com"),
        )
        scheduler_role.add_to_policy(
            iam.PolicyStatement(
                actions=["lambda:InvokeFunction"],
                resources=[fn.function_arn],
            )
        )

        # --- EventBridge Scheduler: weekdays at 23:00 UTC ---
        scheduler.CfnSchedule(
            self,
            "DailySchedule",
            schedule_expression="cron(0 23 ? * MON-FRI *)",
            flexible_time_window=scheduler.CfnSchedule.FlexibleTimeWindowProperty(
                mode="FLEXIBLE",
                maximum_window_in_minutes=15,
            ),
            target=scheduler.CfnSchedule.TargetProperty(
                arn=fn.function_arn,
                role_arn=scheduler_role.role_arn,
                retry_policy=scheduler.CfnSchedule.RetryPolicyProperty(
                    maximum_retry_attempts=0,
                ),
            ),
        )

        # --- SNS Topic for alerts ---
        topic = sns.Topic(self, "AlertTopic", display_name="adrs-warehouse-alerts")
        topic.add_subscription(sns_subs.EmailSubscription(ALERT_EMAIL))

        # --- CloudWatch Alarm: any Lambda error triggers alert ---
        alarm = cloudwatch.Alarm(
            self,
            "ErrorAlarm",
            alarm_name="adrs-warehouse-lambda-errors",
            metric=fn.metric_errors(period=cdk.Duration.days(1)),
            threshold=1,
            evaluation_periods=1,
            comparison_operator=cloudwatch.ComparisonOperator.GREATER_THAN_OR_EQUAL_TO_THRESHOLD,
            treat_missing_data=cloudwatch.TreatMissingData.NOT_BREACHING,
        )
        alarm.add_alarm_action(cw_actions.SnsAction(topic))
