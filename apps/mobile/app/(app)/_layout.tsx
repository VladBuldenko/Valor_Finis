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
    </Stack>
  );
}