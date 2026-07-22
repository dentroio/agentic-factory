FROM hashicorp/vault:1.17

USER root
COPY config.hcl /vault/config/config.hcl
COPY auto-init.sh /auto-init.sh
RUN chmod +x /auto-init.sh && mkdir -p /vault/data /vault/keys

ENV VAULT_ADDR=http://127.0.0.1:8200

CMD ["/auto-init.sh"]
