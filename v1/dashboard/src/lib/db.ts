import { neon } from "@neondatabase/serverless";

export function getDb() {
  const databaseUrl = process.env.NEON_DATABASE_URL;
  if (!databaseUrl) {
    throw new Error("NEON_DATABASE_URL environment variable is not set");
  }
  return neon(databaseUrl);
}
