// Profile-view counter for the GitHub profile README.
//
//   GET /badge.svg     count one view, return the badge (embedded in README.md)
//   GET /history.json  daily view counts, no counting (read by scripts/generate_stats.py)
//
// A single Durable Object holds the count in SQLite so concurrent views
// never race. Days are bucketed in Bangkok time (UTC+7, no DST) to line up
// with the daily stat-card workflow.

import { DurableObject } from "cloudflare:workers";

const BANGKOK_OFFSET_MS = 7 * 60 * 60 * 1000;

export class Counter extends DurableObject {
  constructor(ctx, env) {
    super(ctx, env);
    this.sql = ctx.storage.sql;
    this.sql.exec(`
      CREATE TABLE IF NOT EXISTS daily (date TEXT PRIMARY KEY, views INTEGER NOT NULL);
      CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value INTEGER NOT NULL);
    `);
    // Carry over the pre-existing komarev.com total on first run only
    this.sql.exec(
      "INSERT OR IGNORE INTO meta (key, value) VALUES ('seed', ?)",
      Number(env.SEED_TOTAL ?? 0),
    );
  }

  hit() {
    const day = new Date(Date.now() + BANGKOK_OFFSET_MS).toISOString().slice(0, 10);
    this.sql.exec(
      "INSERT INTO daily (date, views) VALUES (?, 1) " +
        "ON CONFLICT(date) DO UPDATE SET views = views + 1",
      day,
    );
    return this.total();
  }

  total() {
    const seed = this.sql.exec("SELECT value FROM meta WHERE key = 'seed'").one().value;
    const counted = this.sql.exec("SELECT COALESCE(SUM(views), 0) AS n FROM daily").one().n;
    return seed + counted;
  }

  history() {
    return {
      total: this.total(),
      seed: this.sql.exec("SELECT value FROM meta WHERE key = 'seed'").one().value,
      daily: this.sql.exec("SELECT date, views FROM daily ORDER BY date").toArray(),
    };
  }
}

// Flat-square badge in the style of the old komarev.com one. Verdana 11px
// widths are approximated; digits are ~7px.
function badge(label, value, color) {
  const lw = 80;
  const vw = 10 + 7 * String(value).length;
  const w = lw + vw;
  return (
    `<svg xmlns="http://www.w3.org/2000/svg" width="${w}" height="20" role="img" ` +
    `aria-label="${label}: ${value}"><title>${label}: ${value}</title>` +
    `<g shape-rendering="crispEdges"><rect width="${lw}" height="20" fill="#555"/>` +
    `<rect x="${lw}" width="${vw}" height="20" fill="${color}"/></g>` +
    `<g fill="#fff" text-anchor="middle" font-family="Verdana,Geneva,DejaVu Sans,sans-serif" ` +
    `font-size="11"><text x="${lw / 2}" y="14">${label}</text>` +
    `<text x="${lw + vw / 2}" y="14">${value}</text></g></svg>`
  );
}

const NO_CACHE = "max-age=0, no-cache, no-store, must-revalidate";

export default {
  async fetch(request, env) {
    const { pathname } = new URL(request.url);
    const counter = env.COUNTER.get(env.COUNTER.idFromName("vpoonyak"));

    if (pathname === "/badge.svg") {
      const total = await counter.hit();
      return new Response(badge("Profile Views", total, "#0056b3"), {
        headers: { "Content-Type": "image/svg+xml", "Cache-Control": NO_CACHE },
      });
    }
    if (pathname === "/history.json") {
      return Response.json(await counter.history(), {
        headers: { "Cache-Control": NO_CACHE },
      });
    }
    return new Response("Not found", { status: 404 });
  },
};
