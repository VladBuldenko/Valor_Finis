import { StyleSheet } from "react-native";

export const styles = StyleSheet.create({
  container: {
    flex: 1,
  },
  content: {
    paddingHorizontal: 24,
    paddingTop: 32,
    paddingBottom: 32,
  },
  title: {
    fontSize: 32,
    fontWeight: "700",
  },
  subtitle: {
    fontSize: 20,
    marginTop: 8,
  },
  card: {
    marginTop: 32,
    padding: 20,
    borderWidth: 1,
    borderRadius: 12,
  },
  sectionTitle: {
    fontSize: 18,
    fontWeight: "600",
  },
  amount: {
    fontSize: 32,
    fontWeight: "700",
    marginTop: 12,
  },
  secondaryText: {
    fontSize: 16,
    marginTop: 8,
  },
  errorText: {
    fontSize: 16,
    marginTop: 12,
  },
  loader: {
    marginTop: 16,
  },
  categoryList: {
    marginTop: 8,
  },
  categoryRow: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    paddingVertical: 12,
  },
  categoryDetails: {
    flex: 1,
    paddingRight: 16,
  },
  categoryName: {
    fontSize: 16,
    fontWeight: "600",
  },
  categoryAmount: {
    fontSize: 16,
    fontWeight: "600",
  },
  button: {
    alignItems: "center",
    borderWidth: 1,
    borderRadius: 10,
    paddingVertical: 14,
    marginTop: 32,
  },
  buttonText: {
    fontSize: 16,
    fontWeight: "600",
  },
});