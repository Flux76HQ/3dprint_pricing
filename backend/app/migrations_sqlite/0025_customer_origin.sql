-- Where a customer came from (`customers.origin`, see `customers.py`): '' (not said), 'marktplaats', 'webshop' or 'other'. A customer from Marktplaats can also
-- carry the address of their profile there and of the chat with them (`marktplaats_profile_url`, `marktplaats_chat_url`): what you open to answer them, or to
-- look them up again. Only the owner's own bookkeeping: none of it is on an invoice, a label, in `/api/v1` or in a webhook, and an order does not copy it.
--
-- The list of origins is checked by the application (`customers.ORIGINS`), not by a CHECK here: SQLite cannot change a CHECK without rebuilding the table, and a
-- new origin should be one more word in a list. The two addresses are only ever kept while the origin is 'marktplaats' (the application empties them otherwise).
-- Customers that exist already have no origin and no addresses.
ALTER TABLE customers ADD COLUMN origin TEXT NOT NULL DEFAULT '';
ALTER TABLE customers ADD COLUMN marktplaats_profile_url TEXT NOT NULL DEFAULT '';
ALTER TABLE customers ADD COLUMN marktplaats_chat_url TEXT NOT NULL DEFAULT '';
