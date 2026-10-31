import { createAuthOperationQueue } from "../api/auth-operations";

// The one queue every session-changing auth call runs through (see
// api/auth-operations.ts and api/auth-gateway.ts).
export const authOperations = createAuthOperationQueue();
