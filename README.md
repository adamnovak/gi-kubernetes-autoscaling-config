# GI Kubernetes Autoscaling Configuration

This repo contains configuration files that we can use to set up autoscaling nodes on the shared GI Kubernetes cluster.

## Usage:

1. Create a real credentials configuration file:
    ```
    cp kubenode.credentials.cloud-config.yaml.example kubenode.credentials.cloud-config.yaml
    chmod 600 kubenode.credentials.cloud-config.yaml
    ```
2. Edit `kubenode.credentials.cloud-config.yaml` and add the credentials from the leader. You can generate them like:
    ```
    export JOIN_TOKEN=$(kubeadm token create --ttl 0)
    export JOIN_CERT_HASH=sha256:$(openssl x509 -pubkey -in /etc/kubernetes/pki/ca.crt | openssl rsa -pubin -outform der 2>/dev/null | openssl dgst -sha256 -hex | sed 's/^.* //')
    export JOIN_ENDPOINT="$(curl http://checkip.amazonaws.com):6443"
    env | grep "^JOIN_"
    ```
    To check a YAML for syntax, use `cloud-init devel schema -c kubenode.credentials.cloud-config.yaml`.
3. Pack together all the YAML files appropriate for your target AMI into a base64-encoded single-line user data blob. For CentOS 7, you will need to include `kubenode.centos7.cloud-config.yaml`, and for Ubuntu you will need `kubenode.ubuntu.cloud-config.yaml`. You will also need to include the appropriate config YAML for your architecture and spot-ness.
    ```
    umask 0066
    cloud-init devel make-mime \
        -a kubenode.cloud-config.yaml:cloud-config \
        -a kubenode.credentials.cloud-config.yaml:cloud-config \
        -a kubenode.centos7.cloud-config.yaml:cloud-config \
        -a kubenode.config.amd64.ondemand.cloud-config.yaml:cloud-config \
    | gzip -c | base64 | tr -d '\n' > user-data.txt
    ```
    Or for Ubuntu:
    ```
    umask 0066
    cloud-init devel make-mime \
        -a kubenode.cloud-config.yaml:cloud-config \
        -a kubenode.credentials.cloud-config.yaml:cloud-config \
        -a kubenode.ubuntu.cloud-config.yaml:cloud-config \
        -a kubenode.config.amd64.ondemand.cloud-config.yaml:cloud-config \
    | gzip -c | base64 | tr -d '\n' > user-data.txt
    ```
    If your distribution doesn't ship `cloud-init`, you can install it in a Python virtualenv:
    ```
    virtualenv --python python3 venv
    . venv/bin/activate
    pip install https://github.com/canonical/cloud-init/releases/download/21.3/cloud-init-21.3.tar.gz
    ```
4. Put the user data into an AWS Launch Template for the instance type and AMI you want to run, for the `cg-kube` security group. Make sure to check "User data has already been base64 encoded". Make sure to use an AMI that includes cloud-init. [CentOS's official AMIs](https://centos.org/download/aws-images/) might be a good choice. **Don't** check the request spot instance box here; configure that, if applicable, in the Autoscaling Group later.**Do** tag the template with an Owner tag if required; the ASG wil be responsible for tagging the resources.
5. Make an AWS Autoscaling Group around the Launch Template. Use the default VPC's default subnet in `us-west-2b`. Set the minimum size to 0, and the maximum size to a sensible limit.
    Add your instance type manually. **Delete the extra instance types that AWS automatically adds to your ASG**, unless they are exactly the same size and shape as the instance type you are actually using. Otherwise the autoscaler will not be able to rely on the instance actually produced being as big as the main instance type is.
    If using multiple instance types for a spot ASG, you may be best off using capacity-optimized rather than lowest-price balancing; the cheapest spot pool may be full, at which point the whole ASG can't scale up.
    Be sure to give it the following tags (assuming the cluster's name is `gi-cluster`), which should also apply to instances:
    ```
    Name = cg-kube-node
    Owner = <your email>
    kubernetes.io/cluster/cg-kubernetes = <empty>
    k8s.io/cluster-autoscaler/cg-kubernetes = <empty>
    k8s.io/cluster-autoscaler/enabled = <empty>
    k8s.io/cluster-autoscaler/node-template/resources/ephemeral-storage = <amount of ephemeral storage the instances will provide in GiB, like "24G">
    ```
    When computing ephemeral storage, make sure to account for overhead: Partitioning seems to spirit away a bit over a GiB of space, plus there's around half a GiB of images the node will need, and contrary to what https://aws.amazon.com/ec2/instance-types/ says instance ephemeral SSDs are sized in GB. You may also need to account for space that will be allocated to system pods/daemon sets; it's not clear whether the autoscaler accounts for them, and they need about 14 GiB of storage. An underestimate here is safe; an overestimate can get the autoscaler stuck spinning up many of the same node, thinking each time a pod will fit when it won't.
    If using particular labels or taints, such as on spot nodes, you will also need to add those to the ASG itself as tags, so the autoscaler knows that they will apply to the nodes when they come up:
    ```
    k8s.io/cluster-autoscaler/node-template/label/eks.amazonaws.com/capacityType = SPOT
    k8s.io/cluster-autoscaler/node-template/taint/cloud.google.com/gke-preemptible = true:NoSchedule
    ```
    Note that **all tags must be set to propagate to the instance**, or the cluster autoscaler won't see them. See https://github.com/kubernetes/autoscaler/issues/4490.
6. Assuming the Kubernetes Cluster Autoscaler is running on the control plane, it should (eventually?) discover the Autoscaling Group. It might need to be restarted to do it. Then it should start using the Autoscaling Group to provision nodes when it thinks it needs them.

## Cluster Preparation

In order for the cluster to actually scale the Autoscaling Groups, it needs to be running the Cluster Autoscaler. To install it, modify the demplate from the documentation to match the cluster, and apply it:

```
CLUSTER_NAME=cg-kubernetes
AUTOSCALER_VERSION="1.21.1"
curl -sSL https://raw.githubusercontent.com/kubernetes/autoscaler/cluster-autoscaler-${AUTOSCALER_VERSION}/cluster-autoscaler/cloudprovider/aws/examples/cluster-autoscaler-run-on-control-plane.yaml | \
    sed "s|--nodes={{ node_asg_min }}:{{ node_asg_max }}:{{ name }}|--node-group-auto-discovery=asg:tag=k8s.io/cluster-autoscaler/enabled,k8s.io/cluster-autoscaler/${CLUSTER_NAME}|" | \
    sed 's|kubernetes.io/role: master|node-role.kubernetes.io/master: ""|' | \
    sed 's|operator: "Equal"|operator: "Exists"|' | \
    sed '/value: "true"/d' | \
    sed 's|path: "/etc/ssl/certs/ca-bundle.crt"|path: "/etc/pki/ca-trust/extracted/pem/tls-ca-bundle.pem"|' | \
    kubectl apply -f -
```

To work, the leader nodes will need an IAM role assigned (`KubernetesAutoscaler`) with this IAM policy (`MinimalKubernetesAutoscalingPermissions`) attached:

```
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Effect": "Allow",
            "Action": [
                "autoscaling:DescribeAutoScalingGroups",
                "autoscaling:DescribeAutoScalingInstances",
                "autoscaling:DescribeLaunchConfigurations",
                "autoscaling:DescribeTags",
                "autoscaling:SetDesiredCapacity",
                "autoscaling:TerminateInstanceInAutoScalingGroup",
                "ec2:DescribeInstances",
                "ec2:DescribeLaunchTemplateVersions",
                "ec2:DescribeRegions",
                "ec2:DescribeRouteTables",
                "ec2:DescribeSecurityGroups",
                "ec2:DescribeSubnets",
                "ec2:DescribeVolumes",
                "ec2:DescribeVpcs"
            ],
            "Resource": "*"
        }
    ]
}
```

For the autoscaler to work well, you want the cluster's scheduler to pack jobs onto as few nodes as possible. If it spreads the work evenly over all the nodes in the cluster, then having pods that the autoscaler isn't willing to preempt (like non-preemptable Toil jobs) will prevent nodes from scaling down when they aren't needed. All nodes will have a few jobs that block them from being scaled away, and the autoscaler doesn't do anything to cordon nodes and prevent new jobs from landing on them, to try and get an empty node to scale away. You will want to create a config file like this, mount it into your scheduler pods, and set them to use it:

```
# /etc/kubernetes/scheduler-config.yml
apiVersion: kubescheduler.config.k8s.io/v1beta1
kind: KubeSchedulerConfiguration
clientConnection:
  kubeconfig: /etc/kubernetes/scheduler.conf
profiles:
  - schedulerName: default-scheduler
    plugins:
      score:
        disabled:
        - name: NodeResourcesLeastAllocated
        enabled:
        - name: NodeResourcesMostAllocated
          weight: 1
```

To add this setting to an existing cluster, make sure that `/etc/kubernetes/manifests/kube-scheduler.yaml` specifies a `--config` option for the scheduler. You may need the scheduler config file to specify all the options previously passed on the command line, in case the config file overrides them. If the cluster is managed with `kubeadm`, you may be able to rerun the `control-plane/scheduler` phase with a config file like this:

```
# configfile.yaml
apiVersion: kubeadm.k8s.io/v1beta2
kind: ClusterConfiguration
scheduler:
  extraArgs:
    config: "/etc/kubernetes/scheduler-config.yml"
  extraVolumes:
    - name: schedulerconfig
      hostPath: "/etc/kubernetes/scheduler-config.yml"
      mountPath: "/etc/kubernetes/scheduler-config.yml"
      readOnly: true
      pathType: "File"
```

```
kubeadm init phase control-plane scheduler --config=configfile.yaml
```

To get rid of nodes that are scaled away, you will want to make sure you have `jq`, and make an executable `/usr/local/bin/cleanup-nodes.sh`:

```
#!/usr/bin/env bash
# cleanup-nodes.sh: constantly clean up NotReady nodes that are tainted as having been deleted
set -e
while true ; do
    echo "$(date | tr -d '\\n'): Checking for scaled-in nodes..."
    for NODE_NAME in $(kubectl --kubeconfig /etc/kubernetes/admin.conf get nodes -o json | jq -r '.items[] | select(.spec.taints) | select(.spec.taints[] | select(.key == "ToBeDeletedByClusterAutoscaler")) | select(.spec.taints[] | select(.key == "node.kubernetes.io/unreachable")) | select(.status.conditions[] | select(.type == "Ready" and .status == "Unknown")) | .metadata.name' | tr '\n' ' ') ; do
        # For every node that's tainted as ToBeDeletedByClusterAutoscaler, and
        # as node.kubernetes.io/unreachable, and hasn't dialed in recently (and
        # is thus in readiness state Unknown)
        echo "Node $NODE_NAME is supposed to be scaled away and also gone. Removing from cluster..."
        # Drop it if possible
        kubectl --kubeconfig /etc/kubernetes/admin.conf delete node "$NODE_NAME" || true
    done
    sleep 300
done
```

And an `/etc/systemd/system/cleanup-nodes.service`:

```
[Unit]
Description=Remove scaled-in nodes
After=kubelet.service
[Service]
ExecStart=/usr/local/bin/cleanup-nodes.sh
Restart=always
StartLimitInterval=0
RestartSec=10
[Install]
WantedBy=multi-user.target
```

And then enable and start the service:

```
sudo systemctl enable cleanup-nodes
sudo systemctl start cleanup-nodes
```

## Updates and Maintainance

### Changing the Credentials

If you need to rotate the join token or the cluster authentication certificates and hashes, edit `kubenode.credentials.cloud-config.yaml` and rebuild your user data. You will probably have to do this once for spot nodes and once for non-spot nodes, for each architecture in your cluster.

### Recovering Config from Cloud

If an update has been made to a launch template, but not committed back to the repository, you can unpack the individual YAML files from the launch template user data.

Copy-paste the launch template's base64-encoded user data into `userdata.b64`, and then run this command to decode and decompress it, and to unpack the multipart MIME encoding:

```
base64 -d userdata.b64 | zcat - | mha-decode -single /dev/stdin
```

This will overwrite files in the current directory with those embedded in the user data.
