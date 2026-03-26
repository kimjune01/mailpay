# The Stack

Composable open-source components for the full mailpay protocol. The email spec (payment proof format, lifecycle state machine) is the protocol layer. Everything below is infrastructure you compose from existing projects.

## Settlement

| Component | What it does | Link |
|-----------|-------------|------|
| Solana SPL Token Program | USDC transfers, $0.0004/tx | [docs](https://spl.solana.com/token) |
| Sablier | Streaming payments for milestone-based work | [sablier.com](https://sablier.com) |
| OpenZeppelin Escrow | Timelocked pull-payment for refunds | [docs](https://docs.openzeppelin.com/contracts) |

## Identity & Trust

| Component | What it does | Link |
|-----------|-------------|------|
| DKIM/DMARC | Transport-level sender authenticity (already in SMTP) | [RFC 6376](https://www.rfc-editor.org/rfc/rfc6376) |
| ZK Email | Privacy-preserving email-to-wallet binding | [docs.zk.email](https://docs.zk.email/) |
| EAS | On-chain reputation attestations | [attest.org](https://attest.org/) |
| SIWE | Wallet-email binding UX | [login.xyz](https://login.xyz/) |
| Gitcoin Passport | Sybil resistance scoring | [passport.gitcoin.co](https://passport.gitcoin.co/) |
| PageLeft | Copyleft content index, trust signal for agent identity | [pageleft.cc](https://pageleft.cc) |

## Agent Infrastructure

| Component | What it does | Link |
|-----------|-------------|------|
| AgentMail | Managed IMAP/SMTP for agents, one API call | [agentmail.to](https://www.agentmail.to) |
| AWS SES + Lambda | Self-hosted agent email | [docs](https://docs.aws.amazon.com/ses/) |
| Turnkey | Wallet-as-a-service, TEE key management | [turnkey.com](https://www.turnkey.com) |
| Privy | Server-controlled wallet fleets | [privy.io](https://docs.privy.io/) |
| Cloudflare Email Workers | Programmable inbound email handlers | [docs](https://developers.cloudflare.com/email-routing/email-workers/) |

## Disputes & Adjudication

| Component | What it does | Link |
|-----------|-------------|------|
| Kleros | Decentralized arbitration | [kleros.io](https://kleros.io/) |
| Reality.eth | Oracle for dispute outcomes | [reality.eth.limo](https://reality.eth.limo/) |
| ARC headers | Email chain-of-custody for evidence | [RFC 8617](https://www.rfc-editor.org/rfc/rfc8617) |

## Accounting & Compliance

| Component | What it does | Link |
|-----------|-------------|------|
| GnuCash / ERPNext | Double-entry bookkeeping | [gnucash.org](https://gnucash.org/) |
| OpenFisca | Tax rule engine | [openfisca.org](https://openfisca.org/) |
| OpenSanctions | Sanctions screening | [opensanctions.org](https://opensanctions.org/) |
| Travel Rule | DKIM identity may satisfy natively | [FinCEN guidance](https://www.fincen.gov/resources/statutes-regulations/guidance) |

## Spam & Rate Limiting

| Component | What it does | Link |
|-----------|-------------|------|
| Hashcash | Proof-of-work in email headers | [hashcash.org](http://www.hashcash.org/) |
| Sender bonds | Stake USDC to send, forfeit on spam flag | (protocol design needed) |
| DKIM reputation | Domain age + history as trust signal | (scoring design needed) |

## Delivery & Lifecycle

| Component | What it does | Link |
|-----------|-------------|------|
| DSN | SMTP delivery status notifications | [RFC 3464](https://www.rfc-editor.org/rfc/rfc3464) |
| MDN | Message disposition (read receipts) | [RFC 8098](https://www.rfc-editor.org/rfc/rfc8098) |
| ARC | Forwarding chain integrity | [RFC 8617](https://www.rfc-editor.org/rfc/rfc8617) |

## The Spec (in progress)

What doesn't exist yet — the protocol work:

- **Email event → economic state machine.** Standard lifecycle transitions: request → 402 → payment → work → settlement → complete.
- **Milestone language.** Canonical format for partial completion in email-native jobs.
- **Evidence packaging.** How email threads become dispute evidence (headers, DKIM chains, payment proofs bundled).
- **Reputation composition.** Scoring across SMTP history + wallet history + agent performance.
