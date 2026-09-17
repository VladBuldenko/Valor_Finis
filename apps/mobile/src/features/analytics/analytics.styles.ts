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
  noticeText: {
    fontSize: 14,
    marginTop: 8,
  },
  loader: {
    marginTop: 16,
  },
  // Day / Week / Month segmented control. Selection is shown through both
  // a heavier border and bolder text, not color alone.
  periodSwitcher: {
    flexDirection: "row",
    gap: 8,
    marginTop: 12,
  },
  periodButton: {
    flex: 1,
    alignItems: "center",
    borderWidth: 1,
    borderRadius: 8,
    paddingVertical: 10,
  },
  periodButtonSelected: {
    borderWidth: 2,
  },
  periodButtonText: {
    fontSize: 14,
    fontWeight: "500",
  },
  periodButtonTextSelected: {
    fontWeight: "700",
  },
  bucketList: {
    marginTop: 12,
  },
  bucketRow: {
    flexDirection: "row",
    alignItems: "flex-start",
    justifyContent: "space-between",
    paddingVertical: 10,
    borderTopWidth: 1,
  },
  bucketDetails: {
    flex: 1,
    paddingRight: 16,
  },
  bucketRange: {
    fontSize: 15,
    fontWeight: "600",
  },
  bucketAmount: {
    fontSize: 15,
    fontWeight: "600",
  },
  comparisonBox: {
    marginTop: 12,
    paddingTop: 12,
    borderTopWidth: 1,
  },
  categoryBlock: {
    marginTop: 20,
    paddingTop: 12,
    borderTopWidth: 1,
  },
  categoryName: {
    fontSize: 16,
    fontWeight: "700",
  },
});
