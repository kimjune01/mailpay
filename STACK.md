# The Stack

Composable open-source components for the full mailpay protocol. The email spec (payment proof format, lifecycle state machine) is the protocol layer. Everything below is infrastructure you compose from existing projects.

License column shows copyleft (GPL/AGPL/EPL), permissive (MIT/Apache), proprietary, or open standard (RFC). mailpay itself is AGPL-3.0.

## Settlement

| Component | What it does | License | Link |
|-----------|-------------|---------|------|
| Solana SPL Token Program | USDC transfers, $0.0004/tx | Apache 2.0 | [docs](https://spl.solana.com/token) |
| OpenZeppelin Escrow | Timelocked pull-payment for refunds | MIT | [docs](https://docs.openzeppelin.com/contracts) |
| Sequential milestone payments | Each milestone is a separate mailpay email — no streaming contract needed | — | [Certified Mail](https://june.kim/certified-mail) |

## Identity & Trust

| Component | What it does | License | Link |
|-----------|-------------|---------|------|
| DKIM/DMARC | Transport-level sender authenticity | RFC (open standard) | [RFC 6376](https://www.rfc-editor.org/rfc/rfc6376) |
| ZK Email | Privacy-preserving email-to-wallet binding | MIT | [docs.zk.email](https://docs.zk.email/) |
| EAS | On-chain reputation attestations | MIT | [attest.org](https://attest.org/) |
| SIWE | Wallet-email binding UX | Apache 2.0 | [login.xyz](https://login.xyz/) |
| Gitcoin Passport | Sybil resistance scoring | **AGPL-3.0** | [passport.gitcoin.co](https://passport.gitcoin.co/) |
| PageLeft | Copyleft content index, trust signal for agent identity | **AGPL-3.0** | [pageleft.cc](https://pageleft.cc) |

## Agent Infrastructure

| Component | What it does | License | Link |
|-----------|-------------|---------|------|
| Postfix | Battle-tested MTA, self-hosted | **EPL-2.0** | [postfix.org](https://www.postfix.org/) |
| Dovecot | IMAP server, self-hosted | **LGPL-2.1** | [dovecot.org](https://www.dovecot.org/) |
| AgentMail | Managed IMAP/SMTP for agents | Proprietary | [agentmail.to](https://www.agentmail.to) |
| AWS SES + Lambda | Self-hosted agent email | Proprietary | [docs](https://docs.aws.amazon.com/ses/) |
| Turnkey | Wallet-as-a-service, TEE key management | Proprietary | [turnkey.com](https://www.turnkey.com) |
| Privy | Server-controlled wallet fleets | Proprietary | [privy.io](https://docs.privy.io/) |

## Disputes & Adjudication

| Component | What it does | License | Link |
|-----------|-------------|---------|------|
| Reality.eth | Oracle for dispute outcomes | **GPL-3.0** | [reality.eth.limo](https://reality.eth.limo/) |
| Kleros | Decentralized arbitration | MIT | [kleros.io](https://kleros.io/) |
| ARC headers | Email chain-of-custody for evidence | RFC (open standard) | [RFC 8617](https://www.rfc-editor.org/rfc/rfc8617) |

## Accounting & Compliance

| Component | What it does | License | Link |
|-----------|-------------|---------|------|
| GnuCash | Double-entry bookkeeping | **GPL-2.0** | [gnucash.org](https://gnucash.org/) |
| ERPNext | Full ERP with accounting | **GPL-3.0** | [erpnext.com](https://erpnext.com/) |
| OpenFisca | Tax rule engine | **AGPL-3.0** | [openfisca.org](https://openfisca.org/) |
| OpenSanctions | Sanctions screening | MIT | [opensanctions.org](https://opensanctions.org/) |
| Travel Rule | DKIM identity may satisfy natively | RFC (open standard) | [FinCEN guidance](https://www.fincen.gov/resources/statutes-regulations/guidance) |

## Spam & Rate Limiting

| Component | What it does | License | Link |
|-----------|-------------|---------|------|
| SpamAssassin | Content-based spam filtering | Apache 2.0 | [spamassassin.apache.org](https://spamassassin.apache.org/) |
| Hashcash | Proof-of-work in email headers | Public domain | [hashcash.org](http://www.hashcash.org/) |
| Sender bonds | Stake USDC to send, forfeit on spam flag | — | (protocol design needed) |
| DKIM reputation | Domain age + history as trust signal | — | (scoring design needed) |

## Delivery & Lifecycle

| Component | What it does | License | Link |
|-----------|-------------|---------|------|
| DSN | SMTP delivery status notifications | RFC (open standard) | [RFC 3464](https://www.rfc-editor.org/rfc/rfc3464) |
| MDN | Message disposition (read receipts) | RFC (open standard) | [RFC 8098](https://www.rfc-editor.org/rfc/rfc8098) |
| ARC | Forwarding chain integrity | RFC (open standard) | [RFC 8617](https://www.rfc-editor.org/rfc/rfc8617) |

## Copyleft coverage

6 of ~20 components are copyleft. Accounting is the strongest layer (3/4 copyleft). Settlement and identity are almost entirely permissive — crypto projects default to MIT/Apache by convention. Agent infrastructure is mostly proprietary, but the self-hosted path (Postfix + Dovecot + raw IMAP/SMTP) is copyleft all the way down.

The protocol layers (SMTP, DKIM, MIME, DSN, MDN, ARC) are open RFCs — no license needed, anyone can implement. mailpay itself is AGPL-3.0. The copyleft gap is in settlement libraries and identity tooling, where no copyleft alternatives exist yet.

## The Spec (in progress)

What doesn't exist yet — the protocol work:

- **Email event → economic state machine.** Standard lifecycle transitions: request → 402 → payment → work → settlement → complete.
- **Milestone language.** Canonical format for partial completion in email-native jobs.
- **Evidence packaging.** How email threads become dispute evidence (headers, DKIM chains, payment proofs bundled).
- **Reputation composition.** Scoring across SMTP history + wallet history + agent performance.
