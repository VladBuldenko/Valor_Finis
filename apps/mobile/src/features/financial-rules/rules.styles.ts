import { StyleSheet } from "react-native";

import { styles as baseStyles } from "../goals/goals.styles";

// The Goals look is the F3 visual standard (approved design sheet D5): the
// shared styles plus the few extras the rules screens need.
const extra = StyleSheet.create({
  rowBetween: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
  },
  chipRow: {
    flexDirection: "row",
    flexWrap: "wrap",
    marginTop: 8,
  },
  chip: {
    borderWidth: 1,
    borderRadius: 16,
    paddingVertical: 10,
    paddingHorizontal: 14,
    marginRight: 8,
    marginBottom: 8,
    minHeight: 44,
    justifyContent: "center",
  },
  chipSelected: {
    borderWidth: 2,
  },
  chipText: {
    fontSize: 15,
  },
  chipTextSelected: {
    fontWeight: "700",
  },
  statusText: {
    fontSize: 14,
    fontWeight: "700",
    marginTop: 8,
  },
  targetRow: {
    marginTop: 12,
    padding: 12,
    borderWidth: 1,
    borderRadius: 8,
  },
  disabledButton: {
    opacity: 0.5,
  },
  switchRow: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    marginTop: 16,
    minHeight: 44,
  },
  switchLabel: {
    flex: 1,
    fontSize: 16,
    marginRight: 12,
  },
});

export const styles = { ...baseStyles, ...extra };
