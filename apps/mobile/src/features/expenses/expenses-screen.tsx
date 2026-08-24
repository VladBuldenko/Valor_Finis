import { useQuery } from "@tanstack/react-query";
import {
  ActivityIndicator,
  SafeAreaView,
  ScrollView,
  Text,
  View,
} from "react-native";

import { useAuth } from "../auth/auth-context";
import { getExpenses } from "./expense.service";

export function ExpensesScreen() {
  const { session } = useAuth();

  const {
    data: expenses = [],
    isLoading,
    error,
  } = useQuery({
    queryKey: ["expenses", session?.user.id],
    queryFn: getExpenses,
    enabled: Boolean(session),
  });

  return (
    <SafeAreaView>
      <ScrollView>
        <Text>Expenses</Text>

        {isLoading ? (
          <ActivityIndicator />
        ) : error ? (
          <Text>Unable to load expenses.</Text>
        ) : expenses.length === 0 ? (
          <Text>No expenses yet.</Text>
        ) : (
          <View>
            {expenses.map((expense) => (
              <View key={expense.id}>
                <Text>{expense.title}</Text>

                <Text>
                  {expense.amount} {expense.currency}
                </Text>

                <Text>{expense.expense_date}</Text>
              </View>
            ))}
          </View>
        )}
      </ScrollView>
    </SafeAreaView>
  );
}