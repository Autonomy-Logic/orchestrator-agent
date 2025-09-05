# ⚡ Orchestrator Agent
Orchestrator Agent connects with the **Autonomy Edge Cloud Server** and manages **Runtime instances** on the host machine.
It provides secure communication through **mTLS** and supports **WebRTC** and **WebSockets** for real-time orchestration.

## 📖 Table of Contents
- [About](#-about)
- [Tech Stack](#-tech-stack)
- [Installation](#-installation)
- [Running the Agent](#-running-the-agent)
- [Project Structure](#-project-structure)
- [Contributing](#-contributing)
- [License](#-license)

## 💡 About
This agent acts as a bridge between the **Autonomy Edge Cloud Server** and local **Runtime environments**.
It is responsible for:
- Establishing **mutual TLS authentication (mTLS)** with the cloud.
- Managing and orchestrating runtime instances on the local machine.
- Enabling real-time communication using **WebRTC** and **WebSockets**.
- Running inside a **Docker devcontainer** for consistency and portability.

## 🛠️ Tech Stack
- 🐍 **Python 3**
- 🔌 **WebSockets**
- 🔐 **mTLS (mutual TLS authentication)**
- 📡 **WebRTC**
- 🐳 **Docker + VSCode Devcontainers**

 ## ⚙️ Installation
 1. Create a directory for TLS certificates and keys
 ```bash
 mkdir -p ~/.mtls
 ```
 2. Navigate to the directory
 ```bash
 cd ~/.mtls
 ```
 3. Generate TLS certificates using OpenSSL:
    - Create a Certificate Authority
        - Generate the CA private key:
        ```bash
        openssl genrsa -out ca.key 4096
        ```
        - Generate the CA certificate (self-signed, valid for 10 years):
        ```bash
        openssl req -x509 -new -nodes -key ca.key -sha256 -days 3650 -out ca.crt \
        -subj "/C=US/ST=State/L=City/O=MyOrg/OU=CA/CN=MyRootCA"
        ```
    - Create the Client Certi
        - Generate the client private key:
        ```bash
        openssl genrsa -out client.key 4096
        ```
        - Generate a Certificate Signing Request (CSR):
        ```bash
        openssl req -new -key client.key -out client.csr \
        -subj "/C=US/ST=State/L=City/O=MyOrg/OU=Client/CN=client1"
        ```
        - Sign the client certificate with the CA:
        ```bash
        openssl x509 -req -in client.csr -CA ca.crt -CAkey ca.key \
        -CAcreateserial -out client.crt -days 365 -sha256
        ```
4. Open the repository in **VSCode** and start the **devcontainer**.

## 🚀 Running the Agent
Inside the devcontainer:
```bash
python3 src/index.py
```
The agent will connect to the **Autonomy Edge Cloud Server** and begin orchestrating runtimes.

## 📂 Project Structure
```
orchestrator-agent/
├── src/                        
│   ├── controllers/                    # Module for web interface controllers
│   │   ├── websocket_controller/       # Submodule for websocket connections
│   │   └── webrtc_controller/          # Submodule for webrtc connections
│   ├── tools/                          # Module for useful tools
│   │   ├── logger.py                   # Logger tools
│   │   └── ssl.py                      # SSL Context configuration
│   ├── use_cases/                      # Module for specific tasks
│   │   └── docker_manager/             # Submodule for docker-related tasks
│   └── index.py                        # Entry point for the agent
├── .devcontainer/              
│   ├── devcontainer.json               # Configuration for the development container
│   ├── Dockerfile                      # Dockerfile for building the devcontainer environment
│   └── requirements.txt                # Python dependencies
├── .gitignore
└── README.md                           # Project documentation
```

## 🤝 Developing
To start developing in this private repository:

1. Clone the repository using your access credentials.
2. In your browser, access JIRA to find your ticket. Use the JIRA tool to create a branch named after your ticket, following these conventions:
    - Features: `feature/JIRA-123-description`
    - Bugfixes: `bugfix/JIRA-123-description`
    - Hotfixes (for production releases): `hotfix/JIRA-123-description`
3. Pull from the origin and checkout this new branch:
    ```bash
    git pull
    git checkout feature/JIRA-123-description
    ```
4. Make your changes and commit them with clear, descriptive messages.
5. Push your branch to the remote:
    ```bash
    git push origin feature/JIRA-123-description
    ```
6. Open a Pull Request targeting the `development` branch and reference your JIRA ticket.

Please follow the repository's code review and contribution guidelines.