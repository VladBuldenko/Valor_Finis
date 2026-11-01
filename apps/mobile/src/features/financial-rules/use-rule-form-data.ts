import { useQuery } from "@tanstack/react-query";

import { getAccounts } from "../accounts/account.service";
import { useAuth } from "../auth/auth-context";
import { getBudgets } from "../budgets/budget.service";
import { getGoals } from "../goals/goal.service";

// The pickers' source lists. They share the cache entries of the Accounts,
// Goals and Budgets screens (same per-user keys), so no extra requests when
// those are already loaded.
export function useRuleFormData() {
  const { session } = useAuth();
  const userId = session?.user.id;
  const enabled = Boolean(userId);
  const accounts = useQuery({ queryKey: ["accounts", userId], queryFn: getAccounts, enabled });
  const goals = useQuery({ queryKey: ["goals", userId], queryFn: getGoals, enabled });
  const budgets = useQuery({ queryKey: ["budgets", userId], queryFn: getBudgets, enabled });

  return {
    accounts,
    goals,
    budgets,
    isLoading: accounts.isLoading || goals.isLoading || budgets.isLoading,
    isError: accounts.isError || goals.isError || budgets.isError,
    refetchAll: () => {
      void accounts.refetch();
      void goals.refetch();
      void budgets.refetch();
    },
  };
}
