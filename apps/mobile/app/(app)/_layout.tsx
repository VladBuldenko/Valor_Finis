import { Stack } from "expo-router";

export default function AppLayout() {
  return (
    <Stack>
      <Stack.Screen
        name="index"
        options={{
          title: "Valor Finis",
        }}
      />
      <Stack.Screen
        name="budgets"
        options={{
          title: "Budgets",
        }}
      />
      <Stack.Screen
        name="budgets/new"
        options={{
          title: "Add Budget",
        }}
      />
      <Stack.Screen
        name="budgets/[id]/edit"
        options={{
          title: "Edit Budget",
        }}
      />
      <Stack.Screen
        name="categories"
        options={{
          title: "Categories",
        }}
      />
      <Stack.Screen
        name="categories/new"
        options={{
          title: "Add Category",
        }}
      />
      <Stack.Screen
        name="categories/[id]/edit"
        options={{
          title: "Edit Category",
        }}
      />
      <Stack.Screen
        name="expenses"
        options={{
          title: "Expenses",
        }}
      />
      <Stack.Screen
        name="goals"
        options={{
          title: "Goals",
        }}
      />
      <Stack.Screen
        name="goals/new"
        options={{
          title: "Add Goal",
        }}
      />
      <Stack.Screen
        name="goals/[id]/edit"
        options={{
          title: "Edit Goal",
        }}
      />
    </Stack>
  );
}