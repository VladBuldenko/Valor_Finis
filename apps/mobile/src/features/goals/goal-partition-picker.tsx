import { useState } from "react";
import { Modal, Pressable, ScrollView, Text } from "react-native";

import { styles } from "./goals.styles";

export type GoalPartitionPickerOption = {
  key: string;
  label: string;
  // Optional second line (an amount or a capacity hint). Display only.
  detail?: string;
};

type GoalPartitionPickerProps = {
  title: string;
  placeholder: string;
  options: GoalPartitionPickerOption[];
  selectedKey: string | null;
  onChange: (key: string) => void;
  disabled?: boolean;
};

/**
 * Thin "tap to open" bottom-sheet selector (React Native's built-in Modal,
 * like ../accounts/account-picker.tsx) used by the Goal form for the two
 * explicit partition choices of VF-020C3: which Account to reserve from, and
 * which partition to withdraw from. The existing Account pickers cannot show
 * a second line per row, so this one can; everything else matches them.
 *
 * It never preselects, never reorders and never decides anything: it shows
 * the options it is given and reports the user's choice. A selectedKey that
 * is not among the options shows the placeholder, so what is displayed is
 * always what can be submitted.
 */
export function GoalPartitionPicker({
  title,
  placeholder,
  options,
  selectedKey,
  onChange,
  disabled = false,
}: GoalPartitionPickerProps) {
  const [isVisible, setIsVisible] = useState(false);

  const selectedOption = options.find((option) => option.key === selectedKey);

  function handleSelect(key: string) {
    onChange(key);
    setIsVisible(false);
  }

  return (
    <>
      <Pressable
        accessibilityRole="button"
        accessibilityState={{ disabled }}
        disabled={disabled}
        style={styles.selectControl}
        onPress={() => setIsVisible(true)}
      >
        <Text style={styles.selectControlText}>
          {selectedOption ? selectedOption.label : placeholder}
        </Text>

        <Text style={styles.selectControlChevron}>▾</Text>
      </Pressable>

      <Modal
        visible={isVisible}
        transparent
        animationType="slide"
        onRequestClose={() => setIsVisible(false)}
      >
        <Pressable
          style={styles.modalOverlay}
          onPress={() => setIsVisible(false)}
        >
          <Pressable
            style={styles.modalSheet}
            onPress={(event) => event.stopPropagation()}
          >
            <Text style={styles.modalTitle}>{title}</Text>

            <ScrollView style={styles.modalOptionList}>
              {options.map((option) => {
                const isSelected = option.key === selectedKey;

                return (
                  <Pressable
                    key={option.key}
                    style={styles.modalOption}
                    onPress={() => handleSelect(option.key)}
                  >
                    <Text
                      style={[
                        styles.modalOptionText,
                        isSelected && styles.modalOptionSelectedText,
                      ]}
                    >
                      {isSelected ? `✓ ${option.label}` : option.label}
                    </Text>

                    {option.detail ? (
                      <Text style={styles.helperText}>{option.detail}</Text>
                    ) : null}
                  </Pressable>
                );
              })}
            </ScrollView>

            <Pressable
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
