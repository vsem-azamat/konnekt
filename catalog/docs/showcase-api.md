# Making a partner card on the home showcase

For agents making a card on the operator's behalf. The showcase is the three
paid places under «Документы и жизнь» on home: `bank_letter` (the big one),
then `insurance` and `residence`. Each place shows one card at a time. A place
without one invites a partner, «Твоя услуга здесь · Разместить ›», which opens
a sheet leading to `ADS_CONTACT`. With `ADS_CONTACT` unset, it is the plain
tile it always was.

The deal, the photo and the text are agreed with the partner in Telegram. The
card is made only through this API; there is no screen for it in the console.

## Calling it

These are admin routes. They take the console's service token
(`X-Catalog-Service`) and an operator's Telegram id (`X-Catalog-Operator`,
which must be in `ADMIN_TG_IDS`). The edge strips both headers, so a call
comes from inside the production network. The simplest way in is the API's own
container, where the token is already in the environment and never has to be
printed or copied. Save this as `card.py`:

```python
import json, os, re, sys, urllib.error, urllib.request

def call(method, path, body=None, content_type="application/json"):
    data = body if isinstance(body, bytes) or body is None else json.dumps(body).encode()
    request = urllib.request.Request(
        f"http://127.0.0.1:8000/api/v1{path}", data=data, method=method,
        headers={
            "X-Catalog-Service": os.environ["SERVICE_TOKEN"],
            "X-Catalog-Operator": re.findall(r"\d+", os.environ["ADMIN_TG_IDS"])[0],
            "X-Catalog-Lang": "ru",
            "Content-Type": content_type,
        },
    )
    try:
        with urllib.request.urlopen(request) as response:
            return json.load(response)
    except urllib.error.HTTPError as error:
        sys.exit(f"{error.code} {error.read().decode()}")

# What to do this time, for example:
print(json.dumps(call("GET", "/admin/showcase/cards"), ensure_ascii=False, indent=1))
```

and run it in the container, with the photo beside it when there is one:

```bash
scp card.py cover.jpg azamat:/tmp/
ssh azamat 'for f in card.py cover.jpg; do docker cp /tmp/$f supervisor-telegram-catalog-api:/tmp/$f; done
  docker exec supervisor-telegram-catalog-api python /tmp/card.py'
```

`X-Catalog-Lang` is the language the texts are saved in. A reader in another
language sees the card in the first language it has.

## The card

`POST /admin/showcase/cards` saves a **draft**:

```json
{
  "service": "bank_letter",
  "partner": "Lumen Výpis",
  "title": "Выписка для ВНЖ за день",
  "line": "Справка из банка на чешском и английском",
  "text": "Готовим выписку за один рабочий день. Пришлите номер счёта, остальное сделаем сами.",
  "price_from": 290,
  "write_to": "@lumen_vypis",
  "until": "2026-11-30T23:59:00+01:00"
}
```

| Field | Limit | Shown |
| --- | --- | --- |
| `service` | one of the three places | which place |
| `partner` | 200 | under the title; the same name reuses the partner |
| `title` | 32 | the card's heading |
| `line` | 70, optional | the card's two lines under the title |
| `text` | 600, optional | the card's page |
| `price_from` | whole Kč, optional | «от 290 Kč»; without it, no price |
| `write_to` | `https://…` or a Telegram `@username` | where «Написать» leads |
| `until` | a moment with its zone | when the card comes down by itself |

Over a limit is a 422 naming the field: shorten the text, never cut it
mid-word to fit.

Then the photo, as the raw body. JPEG, PNG or WebP, at most 2 MB. The card
shows it at 16:9, cropping the rest, so send 16:9, 1280×720 or larger:

```python
cover = open("/tmp/cover.jpg", "rb").read()
print(call("PUT", "/admin/showcase/cards/41/photo", cover, "image/jpeg"))
```

## Look before publishing

`GET /admin/showcase/cards/{id}/preview` answers exactly what the Mini App
reads for the card, whatever its state, and counts as nobody seeing it. The
photo is at `/api/v1/showcase/photos/{photo}`. Check the title, line and price
read as the partner agreed.

## Publish, and take down

- `POST /admin/showcase/cards/{id}/publish`: live now. A 409 names the card
  holding the place until when; a 422 means no photo yet, or `until` has
  passed.
- `POST /admin/showcase/cards/{id}/unpublish`: down now. Publishing again puts
  it back.
- `PATCH /admin/showcase/cards/{id}`: change only the fields sent. A live card
  shows the change at once. A null clears `line`, `text` or `price_from`.
  To extend a card, send a later `until`.
- `GET /admin/showcase/cards` and `GET /admin/showcase/cards/{id}`: each card's
  `status` (`draft`, `published`, `expired`, `unpublished`) and its last 30
  days of impressions and clicks.

Nothing here deletes anything: a card taken down keeps its numbers and its
photo. When `until` passes, the place is free again without anybody doing
anything.
