# Deployment notes

## Recommended
Browser -> Flask -> SQLite (local) or PostgreSQL (production)

## Bank transfer
- Set `BANK_NAME`, `BANK_ACCOUNT_NUMBER`, `BANK_ACCOUNT_NAME` in environment variables.
- Default account: PalmPay **9015739887**
- Admins must verify each transfer against the payment reference before approving.

## Production checklist
- Long random SECRET_KEY
- HTTPS
- PostgreSQL (set DATABASE_URL)
- Database backups
- Admin access controls
- Rate limiting
- CSRF protection
- Clear risk disclosures
- Legal/regulatory review before public investment activity

## Important
The starter deliberately does not calculate or promise a guaranteed daily return.
Configure any real return model only after it has been legally and financially approved.
