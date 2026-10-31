import { apiRequest } from "../../api/api-client";
import { createFinancialRulesApi } from "./financial-rule.api.ts";

// The app-wide Smart Rules service: the typed API bound to apiRequest, the
// only transport (auth header, deadline, session ownership, GET-only retry).
export const financialRulesService = createFinancialRulesApi(apiRequest);
