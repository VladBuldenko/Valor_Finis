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
        name="goals"
        options={{
          title: "Goals",
        }}
      />
    </Stack>
  );
}