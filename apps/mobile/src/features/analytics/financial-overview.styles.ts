import { StyleSheet } from "react-native";

// Financial Overview (VF-019C). Mirrors ./analytics.styles.ts (cards,
// type scale, notices) so the screen reads as part of Analytics.
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
    marginTop: 24,
    padding: 20,
    borderWidth: 1,
    borderRadius: 12,
  },
  sectionTitle: {
    fontSize: 18,
    fontWeight: "600",
  },
  secondaryText: {
    fontSize: 16,
    marginTop: 8,
  },
  errorText: {
    fontSize: 16,
    marginTop: 12,
  },
  // Incomplete-data warning: bold text plus a border, never color alone.
  warningBox: {
    marginTop: 12,
    padding: 12,
    borderWidth: 2,
    borderRadius: 8,
  },
  warningTitle: {
    fontSize: 15,
    fontWeight: "700",
  },
  warningText: {
    fontSize: 14,
    marginTop: 4,
  },
  noticeText: {
    fontSize: 14,
    marginTop: 8,
  },
  loader: {
    marginTop: 16,
  },
  // --- Month selector: Previous / label / Next ---
  monthSelector: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    marginTop: 20,
  },
  monthButton: {
    minWidth: 96,
    minHeight: 44,
    alignItems: "center",
    justifyContent: "center",
    borderWidth: 1,
    borderRadius: 8,
    paddingHorizontal: 12,
  },
  // A disabled control is dashed (not only dimmed) so its state does not
  // rely on color.
  monthButtonDisabled: {
    borderStyle: "dashed",
    opacity: 0.5,
  },
  monthButtonText: {
    fontSize: 15,
    fontWeight: "600",
  },
  monthLabel: {
    flex: 1,
    textAlign: "center",
    fontSize: 17,
    fontWeight: "700",
    paddingHorizontal: 8,
  },
  // --- Figures (label left, backend value right) ---
  figureList: {
    marginTop: 12,
  },
  figureRow: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "flex-start",
    paddingVertical: 8,
    borderTopWidth: 1,
  },
  figureLabel: {
    fontSize: 15,
    fontWeight: "600",
    paddingRight: 12,
  },
  figureValue: {
    flexShrink: 1,
    fontSize: 15,
    textAlign: "right",
  },
  figureValueStrong: {
    flexShrink: 1,
    fontSize: 15,
    fontWeight: "700",
    textAlign: "right",
  },
  // --- Monthly history ---
  bucketBlock: {
    marginTop: 16,
    paddingTop: 12,
    borderTopWidth: 1,
  },
  bucketTitle: {
    fontSize: 16,
    fontWeight: "700",
  },
  // --- Retry (section-level) ---
  retryButton: {
    alignSelf: "flex-start",
    minHeight: 44,
    justifyContent: "center",
    borderWidth: 1,
    borderRadius: 8,
    paddingHorizontal: 16,
    marginTop: 12,
  },
  retryButtonText: {
    fontSize: 15,
    fontWeight: "600",
  },
});
