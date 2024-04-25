from __future__ import annotations

import time
from typing import TYPE_CHECKING

from cloudshell.cp.core.cancellation_manager import CancellationContextManager

from cloudshell.cp.core.reservation_info import ReservationInfo
from cloudshell.shell.core.resource_driver_interface import ResourceDriverInterface
from cloudshell.shell.core.session.cloudshell_session import CloudShellSessionContext
from cloudshell.shell.core.session.logging_session import LoggingSessionContext

from cloudshell.cp.proxmox.flows import (
    ProxmoxDeleteFlow as DeleteFlow,
    ProxmoxSnapshotFlow as SnapshotFlow,
    ProxmoxAutoloadFlow,
    ProxmoxPowerFlow,
    ProxmoxGetVMDetailsFlow,
)
from cloudshell.cp.proxmox.flows.deploy_flow import get_deploy_params
from cloudshell.cp.proxmox.flows.refresh_ip import refresh_ip

from cloudshell.cp.proxmox.handlers.proxmox_handler import ProxmoxHandler

from cloudshell.cp.proxmox.models.deploy_app import (
    ProxmoxDeployVMRequestActions,
    InstanceFromTemplateDeployApp,
    InstanceFromVMDeployApp,
)
from cloudshell.cp.proxmox.models.deployed_app import (
    ProxmoxDeployedVMActions,
    ProxmoxGetVMDetailsRequestActions,
    InstanceFromTemplateDeployedApp,
    InstanceFromVMDeployedApp,
)
from cloudshell.cp.proxmox.resource_config import ProxmoxResourceConfig

if TYPE_CHECKING:
    from cloudshell.shell.core.driver_context import (
        AutoLoadCommandContext,
        AutoLoadDetails,
        CancellationContext,
        InitCommandContext,
        ResourceCommandContext,
        ResourceRemoteCommandContext,
    )


class ProxmoxCloudProviderShell2GDriver(ResourceDriverInterface):
    def cleanup(self):
        pass

    def __init__(self):
        for deploy_app_cls in (
            InstanceFromVMDeployApp,
            InstanceFromTemplateDeployApp,
        ):
            ProxmoxDeployVMRequestActions.register_deployment_path(deploy_app_cls)

        for deployed_app_cls in (
            InstanceFromVMDeployedApp,
            InstanceFromTemplateDeployedApp,
        ):
            ProxmoxDeployedVMActions.register_deployment_path(deployed_app_cls)

    def initialize(self, context: InitCommandContext):
        pass

    def get_inventory(self, context: AutoLoadCommandContext) -> AutoLoadDetails:
        """Called when the cloud provider resource is created in the inventory.

        Method validates the values of the cloud provider attributes, entered by
        the user as part of the cloud provider resource creation. In addition,
        this would be the place to assign values programmatically to optional
        attributes that were not given a value by the user. If one of the
        validations failed, the method should raise an exception
        :param context: the context the command runs on
        :return Attribute and sub-resource information for the Shell resource
        you can return an AutoLoadDetails object
        """
        with LoggingSessionContext(context) as logger:
            logger.info("Starting Autoload command")
            api = CloudShellSessionContext(context).get_api()
            resource_config = ProxmoxResourceConfig.from_context(context, api=api)

            with ProxmoxHandler.from_config(resource_config) as si:
                autoload_flow = ProxmoxAutoloadFlow(si, resource_config)
                return autoload_flow.discover()

    def Deploy(
        self,
        context: ResourceCommandContext,
        request: str,
        cancellation_context: CancellationContext,
    ) -> str:
        """Called when reserving a sandbox during setup.

        Method creates the compute resource in the cloud provider - VM instance or
        container. If App deployment fails, return a "success false" action result.
        :param request: A JSON string with the list of requested deployment actions
        """
        with LoggingSessionContext(context) as logger:
            logger.info("Starting Deploy command")
            logger.debug(f"Request: {request}")
            cs_api = CloudShellSessionContext(context).get_api()
            resource_config = ProxmoxResourceConfig.from_context(context, api=cs_api)

            cancellation_manager = CancellationContextManager(cancellation_context)
            reservation_info = ReservationInfo.from_resource_context(context)

            request_actions = ProxmoxDeployVMRequestActions.from_request(
                request,
                cs_api
            )
            deploy_flow_class, deploy_instance_type = get_deploy_params(request_actions)
            api = ProxmoxHandler.from_config(resource_config)

            # with ProxmoxHandler.from_config(resource_config) as api:
            deploy_flow = deploy_flow_class(
                api=api,
                resource_config=resource_config,
                reservation_info=reservation_info,
                cs_api=cs_api,
                cancellation_manager=cancellation_manager,
            )
            return deploy_flow.deploy(request_actions=request_actions)

    def PowerOn(self, context: ResourceRemoteCommandContext, ports: list[str]):
        """Called when reserving a sandbox during setup.

        Call for each app in the sandbox can also be run manually by
        the sandbox end-user from the deployed App's commands pane.
        Method spins up the VM If the operation fails, method should raise an exception.
        """
        with LoggingSessionContext(context) as logger:
            logger.info("Starting Power On command")
            api = CloudShellSessionContext(context).get_api()
            resource_config = ProxmoxResourceConfig.from_context(context, api=api)
            resource = context.remote_endpoints[0]
            actions = ProxmoxDeployedVMActions.from_remote_resource(resource, api)
            with ProxmoxHandler.from_config(resource_config) as si:
                return ProxmoxPowerFlow(
                    si, actions.deployed_app, resource_config
                ).power_on()

    def PowerOff(self, context: ResourceRemoteCommandContext, ports: list[str]):
        """Called during sandbox's teardown.

        Can also be run manually by the sandbox end-user from the deployed
        App's commands pane. Method shuts down (or powers off) the VM instance.
        If the operation fails, method should raise an exception.
        """
        with LoggingSessionContext(context) as logger:
            logger.info("Starting Power Off command")
            api = CloudShellSessionContext(context).get_api()
            resource_config = ProxmoxResourceConfig.from_context(context, api=api)
            resource = context.remote_endpoints[0]
            actions = ProxmoxDeployedVMActions.from_remote_resource(resource, api)
            with ProxmoxHandler.from_config(resource_config) as si:
                return ProxmoxPowerFlow(
                    si, actions.deployed_app, resource_config
                ).power_off()

    def PowerCycle(
        self, context: ResourceRemoteCommandContext, ports: list[str], delay
    ):
        with LoggingSessionContext(context) as logger:
            logger.info("Starting Power Cycle command")
            api = CloudShellSessionContext(context).get_api()
            resource_config = ProxmoxResourceConfig.from_context(context, api=api)
            resource = context.remote_endpoints[0]
            actions = ProxmoxDeployedVMActions.from_remote_resource(resource, api)
            with ProxmoxHandler.from_config(resource_config) as si:
                power_flow = ProxmoxPowerFlow(si, actions.deployed_app, resource_config)
                power_flow.power_off()
                time.sleep(float(delay))
                power_flow.power_on()

    def remote_refresh_ip(
        self,
        context: ResourceRemoteCommandContext,
        cancellation_context: CancellationContext,
        ports: list[str],
    ):
        """Called when reserving a sandbox during setup.

        Call for each app in the sandbox can also be run manually by the sandbox
        end-user from the deployed App's commands pane. Method retrieves the VM's
        updated IP address from the cloud provider and sets it on the deployed App
        resource. Both private and public IPs are retrieved, as appropriate. If the
        operation fails, method should raise an exception.
        """
        with LoggingSessionContext(context) as logger:
            logger.info("Starting Remote Refresh IP command")
            api = CloudShellSessionContext(context).get_api()
            resource_config = ProxmoxResourceConfig.from_context(context, api=api)
            resource = context.remote_endpoints[0]
            actions = ProxmoxDeployedVMActions.from_remote_resource(resource, api)
            cancellation_manager = CancellationContextManager(cancellation_context)
            with ProxmoxHandler.from_config(resource_config) as si:
                return refresh_ip(
                    si, actions.deployed_app, resource_config, cancellation_manager
                )

    def GetVmDetails(
        self,
        context: ResourceCommandContext,
        requests: str,
        cancellation_context: CancellationContext,
    ):
        """Called when reserving a sandbox during setup.

        Call for each app in the sandbox can also be run manually by the sandbox
        end-user from the deployed App's VM Details pane. Method queries cloud provider
        for instance operating system, specifications and networking information and
        returns that as a json serialized driver response containing a list of
        VmDetailsData. If the operation fails, method should raise an exception.
        """
        with LoggingSessionContext(context) as logger:
            logger.info("Starting Get VM Details command")
            logger.debug(f"Requests: {requests}")
            api = CloudShellSessionContext(context).get_api()
            resource_config = ProxmoxResourceConfig.from_context(context, api=api)
            cancellation_manager = CancellationContextManager(cancellation_context)
            actions = ProxmoxGetVMDetailsRequestActions.from_request(requests, api)
            with ProxmoxHandler.from_config(resource_config) as si:
                return ProxmoxGetVMDetailsFlow(
                    si, resource_config, cancellation_manager
                ).get_vm_details(actions)

    def ApplyConnectivityChanges(self, context: ResourceCommandContext, request: str):
        with LoggingSessionContext(context) as logger:
            logger.info("Starting Apply Connectivity Changes command")
            api = CloudShellSessionContext(context).get_api()
            resource_config = ProxmoxResourceConfig.from_context(context, api=api)
            reservation_info = ReservationInfo.from_resource_context(context)
            # with ProxmoxHandler.from_config(resource_config) as si:
            #     return ProxmoxConnectivityFlow(
            #         si,
            #         resource_config,
            #         reservation_info,
            #     ).apply_connectivity(request)

    def DeleteInstance(self, context: ResourceRemoteCommandContext, ports: list[str]):
        """Called when removing a deployed App from the sandbox.

        Method deletes the VM from the cloud provider. If the operation fails, method
        should raise an exception.
        """
        with LoggingSessionContext(context) as logger:
            logger.info("Starting Delete Instance command")
            api = CloudShellSessionContext(context).get_api()
            resource_config = ProxmoxResourceConfig.from_context(context, api=api)
            resource = context.remote_endpoints[0]
            actions = ProxmoxDeployedVMActions.from_remote_resource(resource, api)
            try:
                reservation_info = ReservationInfo.from_remote_resource_context(context)
            except AttributeError:
                # The sandbox in which the app is deployed failed and was removed.
                # And the command was called not in the sandbox
                reservation_info = None
            with ProxmoxHandler.from_config(resource_config) as si:
                DeleteFlow(si, actions.deployed_app, resource_config).delete()

    # def SaveApp(
    #     self,
    #     context: ResourceCommandContext,
    #     request: str,
    #     cancellation_context: CancellationContext,
    # ) -> str:
    #     with LoggingSessionContext(context) as logger:
    #         logger.info("Starting Save App command")
    #         api = CloudShellSessionContext(context).get_api()
    #         resource_config = ProxmoxResourceConfig.from_context(context, api=api)
    #         cancellation_manager = CancellationContextManager(cancellation_context)
    #         actions = SaveRestoreRequestActions.from_request(request)
    #         with ProxmoxHandler.from_config(resource_config) as si:
    #             return SaveRestoreAppFlow(
    #                 si, resource_config, api, cancellation_manager
    #             ).save_apps(actions.save_app_actions)
    #
    # def DeleteSavedApps(
    #     self,
    #     context: UnreservedResourceCommandContext,
    #     request: str,
    #     cancellation_context: CancellationContext,
    # ) -> str:
    #     with LoggingSessionContext(context) as logger:
    #         logger.info("Starting Delete Saved App command")
    #         api = CloudShellSessionContext(context).get_api()
    #         resource_config = ProxmoxResourceConfig.from_context(context, api=api)
    #         cancellation_manager = CancellationContextManager(cancellation_context)
    #         actions = SaveRestoreRequestActions.from_request(request)
    #         with ProxmoxHandler.from_config(resource_config) as si:
    #             return SaveRestoreAppFlow(
    #                 si, resource_config, api, cancellation_manager
    #             ).delete_saved_apps(actions.delete_saved_app_actions)

    def remote_save_snapshot(
        self,
        context: ResourceRemoteCommandContext,
        ports: list[str],
        snapshot_name: str,
        save_memory: str,
    ) -> str:
        """Saves virtual machine to a snapshot."""
        with LoggingSessionContext(context) as logger:
            logger.info("Starting Remote Save Snapshot command")
            api = CloudShellSessionContext(context).get_api()
            resource_config = ProxmoxResourceConfig.from_context(context, api=api)
            resource = context.remote_endpoints[0]
            actions = ProxmoxDeployedVMActions.from_remote_resource(resource, api)
            with ProxmoxHandler.from_config(resource_config) as si:
                return SnapshotFlow(
                    si,
                    actions.deployed_app,
                    resource_config,
                ).save_snapshot(snapshot_name, save_memory)

    def remote_restore_snapshot(
        self,
        context: ResourceRemoteCommandContext,
        ports: list[str],
        snapshot_name: str,
    ):
        """Restores virtual machine from a snapshot."""
        with LoggingSessionContext(context) as logger:
            logger.info("Starting Remote Restore Snapshot command")
            api = CloudShellSessionContext(context).get_api()
            resource_config = ProxmoxResourceConfig.from_context(context, api=api)
            resource = context.remote_endpoints[0]
            actions = ProxmoxDeployedVMActions.from_remote_resource(resource, api)
            with ProxmoxHandler.from_config(resource_config) as si:
                return SnapshotFlow(
                    si,
                    actions.deployed_app,
                    resource_config,
                ).restore_from_snapshot(api, snapshot_name)

    def remote_get_snapshots(
        self, context: ResourceRemoteCommandContext, ports: list[str]
    ) -> str:
        """Returns list of snapshots."""
        with LoggingSessionContext(context) as logger:
            logger.info("Starting Remote Get Snapshots command")
            api = CloudShellSessionContext(context).get_api()
            resource_config = ProxmoxResourceConfig.from_context(context, api=api)
            resource = context.remote_endpoints[0]
            actions = ProxmoxDeployedVMActions.from_remote_resource(resource, api)
            with ProxmoxHandler.from_config(resource_config) as si:
                return SnapshotFlow(
                    si,
                    actions.deployed_app,
                    resource_config,
                ).get_snapshot_list()

    def remote_remove_snapshot(
        self,
        context: ResourceRemoteCommandContext,
        ports: list[str],
        snapshot_name: str,
    ):
        with LoggingSessionContext(context) as logger:
            logger.info("Starting Remote Remove Snapshot command")
            api = CloudShellSessionContext(context).get_api()
            resource_config = ProxmoxResourceConfig.from_context(context, api=api)
            resource = context.remote_endpoints[0]
            actions = ProxmoxDeployedVMActions.from_remote_resource(resource, api)
            with ProxmoxHandler.from_config(resource_config) as si:
                return SnapshotFlow(
                    si,
                    actions.deployed_app,
                    resource_config,
                ).remove_snapshot(snapshot_name)

    def orchestration_save(
        self,
        context: ResourceRemoteCommandContext,
        ports: list[str],
        mode: str = "shallow",
        custom_params=None,
    ) -> str:
        with LoggingSessionContext(context) as logger:
            logger.info("Starting Orchestration Save command")
            api = CloudShellSessionContext(context).get_api()
            resource_config = ProxmoxResourceConfig.from_context(context, api=api)
            resource = context.remote_endpoints[0]
            actions = ProxmoxDeployedVMActions.from_remote_resource(resource, api)
            with ProxmoxHandler.from_config(resource_config) as si:
                return SnapshotFlow(
                    si,
                    actions.deployed_app,
                    resource_config,
                ).orchestration_save()

    def orchestration_restore(
        self,
        context: ResourceRemoteCommandContext,
        ports: list[str],
        saved_details: str,
    ):
        with LoggingSessionContext(context) as logger:
            logger.info("Starting Orchestration Restore command")
            api = CloudShellSessionContext(context).get_api()
            resource_config = ProxmoxResourceConfig.from_context(context, api=api)
            resource = context.remote_endpoints[0]
            actions = ProxmoxDeployedVMActions.from_remote_resource(resource, api)
            with ProxmoxHandler.from_config(resource_config) as si:
                return SnapshotFlow(
                    si,
                    actions.deployed_app,
                    resource_config,
                ).orchestration_restore(saved_details, api)

