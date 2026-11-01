import { useState } from "react";
import { Modal, Pressable, ScrollView, Text } from "react-native";

import { styles } from "./rules.styles";

export type PickerOption = { id: string; label: string };

type OptionPickerProps = {
  title: string;
  placeholder: string;
  options: PickerOption[];
  selectedId: string | null;
  onChange: (id: string) => void;
  disabled?: boolean;
};

// A "tap to open" single-choice bottom sheet (same pattern as AccountPicker,
// without a "none" option: rule fields are required). It only lists what it
// is given; ownership, status and currency are enforced by the backend.
export function OptionPicker({
  title,
  placeholder,
  options,
  selectedId,
  onChange,
  disabled = false,
}: OptionPickerProps) {
  const [isVisible, setIsVisible] = useState(false);
  const selected = options.find((option) => option.id === selectedId);
  const selectedLabel = selected
    ? selected.label
    : selectedId === null
      ? placeholder
      : "Unavailable item";

  return (
    <>
      <Pressable
        accessibilityRole="button"
        accessibilityLabel={`${title}: ${selectedLabel}`}
        accessibilityState={{ disabled }}
        disabled={disabled}
        style={[styles.selectControl, disabled && styles.disabledButton]}
        onPress={() => setIsVisible(true)}
      >
        <Text style={styles.selectControlText}>{selectedLabel}</Text>
        <Text style={styles.selectControlChevron}>▾</Text>
      </Pressable>

      <Modal
        visible={isVisible}
        transparent
        animationType="slide"
        onRequestClose={() => setIsVisible(false)}
      >
        <Pressable style={styles.modalOverlay} onPress={() => setIsVisible(false)}>
          <Pressable style={styles.modalSheet} onPress={(event) => event.stopPropagation()}>
            <Text style={styles.modalTitle} accessibilityRole="header">
              {title}
            </Text>

            <ScrollView style={styles.modalOptionList}>
              {options.length === 0 ? (
                <Text style={styles.secondaryText}>Nothing to choose from.</Text>
              ) : null}

              {options.map((option) => {
                const isSelected = option.id === selectedId;

                return (
                  <Pressable
                    key={option.id}
                    accessibilityRole="radio"
                    accessibilityState={{ checked: isSelected }}
                    accessibilityLabel={option.label}
                    style={styles.modalOption}
                    onPress={() => {
                      onChange(option.id);
                      setIsVisible(false);
                    }}
                  >
                    <Text
                      style={[styles.modalOptionText, isSelected && styles.modalOptionSelectedText]}
                    >
                      {isSelected ? `✓ ${option.label}` : option.label}
                    </Text>
                  </Pressable>
                );
              })}
            </ScrollView>

            <Pressable
              accessibilityRole="button"
              style={styles.modalCloseButton}
              onPress={() => setIsVisible(false)}
            >
              <Text style={styles.buttonText}>Close</Text>
            </Pressable>
          </Pressable>
        </Pressable>
      </Modal>
    </>
  );
}
