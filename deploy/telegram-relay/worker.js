// Telegram and Russian clouds can't reach each other directly, Cloudflare reaches both.
// Outgoing: the bot's calls go on to api.telegram.org, only this bot's, so the relay
// can't be borrowed by strangers. Incoming: Telegram's webhook and the files Telegram
// fetches by link (including the bot's static pictures) are passed back to the app at
// ORIGIN.
export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    const outgoing = [`/bot${env.BOT_ID}:`, `/file/bot${env.BOT_ID}:`];
    if (outgoing.some((prefix) => url.pathname.startsWith(prefix))) {
      return fetch(new Request("https://api.telegram.org" + url.pathname + url.search, request));
    }
    const incoming =
      (request.method === "POST" && url.pathname === "/telegram/webhook") ||
      (request.method === "GET" && /^\/(files|static)\//.test(url.pathname));
    if (incoming && env.ORIGIN) {
      return fetch(new Request(env.ORIGIN + url.pathname + url.search, request));
    }
    return new Response("Not found", { status: 404 });
  },
};
