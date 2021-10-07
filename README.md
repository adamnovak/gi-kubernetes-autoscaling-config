# GI Kubernetes Autoscaling Configuration

This repo contains configuration files that we can use to set up autoscaling nodes on the shared GI Kubernetes cluster.

## Usage:

1. Create a real credentials configuration file:
    ```
    cp kubenode.credentials.cloud-config.yaml.example kubenode.credentials.cloud-config.yaml
    ```
2. Edit `kubenode.credentials.cloud-config.yaml` and add the credentials from the leader. You can generate them like:
    ```
    export JOIN_TOKEN=$(kubeadm token create --ttl 0)
    export JOIN_CERT_HASH=sha256:$(openssl x509 -pubkey -in /etc/kubernetes/pki/ca.crt | openssl rsa -pubin -outform der 2>/dev/null | openssl dgst -sha256 -hex | sed 's/^.* //')
    export JOIN_ENDPOINT="$(hostname):6443"
    env | grep "^JOIN_"
    ```
3. Pack together all the YAML files appropriate for your target AMI into a base64-encoded single-line user data blob. For CentOS 7, you will need to include `kubenode.centos7.cloud-config.yaml`, while for a Flatcar AMI you should not (although Flatcar's ignition may not actually understand the gzip/mime-multipart encoding or some of the cloud-config keys used).
    ```
    cloud-init devel make-mime \
        -a kubenode.cloud-config.yaml:cloud-config \
        -a kubenode.credentials.cloud-config.yaml:cloud-config \
        -a kubenode.centos7.cloud-config.yaml:cloud-config \
    | gzip -c | base64 | tr -d '\n' > user-data.txt
    ```
    If your distribution doesn't ship `cloud-init`, you can install it in a Python virtualenv:
    ```
    virtualenv --python python3 venv
    . venv/bin/activate
    pip install https://github.com/canonical/cloud-init/releases/download/21.3/cloud-init-21.3.tar.gz
    ```
4. Put the user data into an AWS Launch Template for the instance type and AMI you want to run. Make sure to check "User data has already been base64 encoded". Make sure to use an AMI that includes cloud-init. [CentOS's official AMIs](https://centos.org/download/aws-images/) might be a good choice.
5. Make an AWS Autoscaling Group around the Launch Template. Be sure to give it the following tags (assuming the cluster's name is `gi-cluster`), which should also apply to instances:
    ```
    Owner=<your email>
    kubernetes.io/cluster/gi-cluster=
    ```
    And the following tags just on the Autoscaling Group itself:
    ```
    k8s.io/cluster-autoscaler/gi-cluster=
    k8s.io/cluster-autoscaler/enabled=
    k8s.io/cluster-autoscaler/node-template/resources/ephemeral-storage=<amount of ephemeral storage the instances will provide, like "24G">
    ```
6. Assuming the Kubernetes Cluster Autoscaler is running on the control plane, it should (eventually?) discover the Autoscaling Group. It might need to be restarted to do it. Then it should start using the Autoscaling Group to provision nodes when it thinks it needs them.
    
     
