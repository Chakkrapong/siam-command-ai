import { NextResponse } from "next/server";
import { getAuthenticatedUser } from "@/lib/server/session";
import { getAllAgentStatuses } from "@/lib/server/agent-status";

export async function GET() {
  const user = await getAuthenticatedUser();

  if (!user) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  }

  const statuses = await getAllAgentStatuses();
  return NextResponse.json({ statuses });
}
