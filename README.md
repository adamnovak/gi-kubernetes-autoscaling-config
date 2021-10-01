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
3. Pack together all the YAML files appropriate for your target AMI into a base64-encoded user data blob. For CentOS 7, you will need to include `kubenode.centos7.cloud-config.yaml`, while for a Flatcar AMI you should not (although Flatcar's ignition may not actually understand the gzip/mime-multipart encoding or some of the cloud-config keys used).
    ```
    cloud-init devel make-mime \
        -a kubenode.cloud-config.yaml:cloud-config \
        -a kubenode.credentials.cloud-config.yaml:cloud-config \
        -a kubenode.centos7.cloud-config.yaml:cloud-config \
    | gzip -c | base64 > user-data.txt
    ```
4. Put the user data into an AWS Launch Template for the instance type and AMI you want to run. Make sure to use an AMI that includes cloud-init.
5. Make an AWS Autoscaling Group around the Launch Template. Be sure to give it the following tags (assuming the cluster's name is `gi-cluster`), which should also apply to instances:
    ```
    Owner=<your email>
    kubernetes.io/cluster/gi-kubernetes=
    k8s.io/cluster-autoscaler/gi-kubernetes=
    k8s.io/cluster-autoscaler/enabled=
    k8s.io/cluster-autoscaler/node-template/resources/ephemeral-storage=<amount of ephemeral storage the instances will provide, like "24G">
    ```
6. Assuming the Kubernetes Cluster Autoscaler is running on the control plane, it should (eventually?) discover the Autoscaling Group. It might need to be restarted to do it. Then it should start using the Autoscaling Group to provision nodes when it thinks it needs them.
    
     
