# MCUBE agent alignment (ops)

Clara matches inbound agents primarily by **`empemail`** from the MCUBE hangup payload to **`users.email`** (case-insensitive).

## Required before go-live

1. For every MCUBE employee who answers Arihant DIDs, ensure a Clara user exists whose **email exactly matches** MCUBE `empemail` (example live sample: `malathy@arihants.co.in`).
2. Optional phone fallback: set `mcube_number` on the user document (same digits as MCUBE `callto` / `empnumber`). On write, also set `normalized_mcube_number` via `normalize_phone()` (last 10 digits). Sparse unique index: `users_normalized_mcube_number_uq_sparse`.

## Example Mongo update (phone fallback)

```js
// After computing normalized_mcube_number = last-10 digits of mcube_number
db.users.updateOne(
  { email: "malathy@arihants.co.in" },
  { $set: { mcube_number: "9841544444", normalized_mcube_number: "9841544444" } }
)
```

Email alignment is enough for V1 if every hangup includes `empemail`.
