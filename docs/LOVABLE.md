# Adding the copilot to the Lovable sites

Do this **after** the API is deployed and `/health` responds. Replace `API_URL` with your Render address, e.g. `https://business-copilot.onrender.com`.

## Harris & Sons (harrisandsons.lovable.app)

Paste into the Lovable chat for the Harris & Sons project:

> Add an external chat widget to every page. In `index.html`, just before the closing `</body>` tag, add exactly this line and nothing else:
> `<script src="API_URL/widget.js" data-persona="harris_sons" async></script>`
> Do not install packages, create components, or change any other file. Also, on the "Book a call" area of the homepage, add a secondary button labelled "Ask the hiring copilot" whose onClick calls `window.BusinessCopilot?.open()`.

## VERAXIS (xveraxis.lovable.app)

> Add an external chat widget to every page. In `index.html`, just before the closing `</body>` tag, add exactly this line and nothing else:
> `<script src="API_URL/widget.js" data-persona="veraxis" async></script>`
> Do not install packages, create components, or change any other file.

## Check it worked

1. Open the published site (not the Lovable editor preview — the editor runs on a different address that the API does not allow).
2. The chat button appears bottom-right. Ask a starter question.
3. If the button never appears: open the browser console. A 403 means the site's address is missing from `allowed_origins` in `personas/<id>/persona.json`; a failed `widget.js` request means `API_URL` is wrong or the Render service is asleep.

To test inside the Lovable editor preview, add its address to `EXTRA_ALLOWED_ORIGINS` on Render temporarily.
