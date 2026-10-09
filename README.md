# Brent Investment Platform

Premium black & purple Flask investment platform for Africans worldwide.

- ₦600 welcome balance on signup (immediate)
- Bank transfer deposits (PalmPay) — pending until admin approves
- Withdrawals — pending until admin approves
- Mobile-friendly nav with hamburger toggle
- Custom Brent logo

## Run on Windows (no venv)

```powershell
cd rocky_fixed
python -m pip install --user -r requirements.txt
python app.py
```

Open http://127.0.0.1:5000

Admin: admin@example.com / ChangeThisImmediately123!

## Change account name

Edit `.env`:
```
BANK_ACCOUNT_NAME=Your Name Here
```
Then restart the app.

If you already ran an older version, delete `investment.db` so the new brand and tables refresh.
