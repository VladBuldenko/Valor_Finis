import { useState } from "react";
import { useRouter } from "expo-router";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import * as ImagePicker from "expo-image-picker";
import {
  ActivityIndicator,
  Alert,
  Button,
  Image,
  SafeAreaView,
  ScrollView,
  Text,
  View,
} from "react-native";

import {
  getReceiptById,
  processReceipt,
  uploadReceipt,
} from "./receipt.service";
import type { PickedReceiptImage } from "./receipt.types";

export function ReceiptUploadScreen() {
  const queryClient = useQueryClient();
  const router = useRouter();

  const [selectedImage, setSelectedImage] =
    useState<PickedReceiptImage | null>(null);
  // Tracks a receipt that uploaded successfully but failed OCR processing,
  // so the user can retry processing without re-uploading the image.
  const [failedReceiptId, setFailedReceiptId] = useState<string | null>(
    null,
  );
  // Guards the window between a picker tap and the mutation actually
  // starting, since opening the native picker UI is not itself a mutation.
  const [isPicking, setIsPicking] = useState(false);

  const uploadMutation = useMutation({
    mutationFn: uploadReceipt,

    onError: (error) => {
      setSelectedImage(null);

      const message =
        error instanceof Error
          ? error.message
          : "Unable to upload receipt.";

      Alert.alert("Upload failed", message);
    },
  });

  const processMutation = useMutation({
    mutationFn: processReceipt,

    onSuccess: (receipt) => {
      // Seed the review screen's query cache so it renders instantly
      // instead of waiting on a second network round trip.
      queryClient.setQueryData(
        ["receipts", "detail", receipt.id],
        receipt,
      );

      setSelectedImage(null);
      setFailedReceiptId(null);

      router.push({
        pathname: "/receipts/[id]",
        params: { id: receipt.id },
      });
    },

    onError: async (error, receiptId) => {
      // The process request can fail on the client (timeout, backgrounded
      // app, dropped connection) even though the server actually finished
      // OCR successfully. Check the receipt's real current status before
      // showing a "failed" screen, so a receipt that already succeeded
      // server-side is never stranded behind a stuck retry loop.
      try {
        const currentReceipt = await getReceiptById(receiptId);

        if (
          currentReceipt.status === "processed" ||
          currentReceipt.status === "confirmed"
        ) {
          queryClient.setQueryData(
            ["receipts", "detail", currentReceipt.id],
            currentReceipt,
          );

          setSelectedImage(null);
          setFailedReceiptId(null);

          router.push({
            pathname: "/receipts/[id]",
            params: { id: currentReceipt.id },
          });

          return;
        }
      } catch {
        // Status check itself failed (e.g. offline) -- fall through to
        // the generic retry UI below.
      }

      setFailedReceiptId(receiptId);

      const message =
        error instanceof Error
          ? error.message
          : "Unable to read this receipt. You can retry or enter the details manually.";

      Alert.alert("Processing failed", message);
    },
  });

  const isBusy =
    isPicking || uploadMutation.isPending || processMutation.isPending;

  async function runScanPipeline(image: PickedReceiptImage) {
    setSelectedImage(image);
    setFailedReceiptId(null);

    try {
      const uploadedReceipt = await uploadMutation.mutateAsync(image);

      await processMutation.mutateAsync(uploadedReceipt.id);
    } catch {
      // Failures are already surfaced through the mutation onError
      // handlers above; this catch only prevents an unhandled rejection.
    }
  }

  async function handlePickFromLibrary() {
    if (isBusy) {
      return;
    }

    setIsPicking(true);

    try {
      const permission =
        await ImagePicker.requestMediaLibraryPermissionsAsync();

      if (!permission.granted) {
        Alert.alert(
          "Permission required",
          "Allow photo library access to attach a receipt.",
        );
        return;
      }

      const result = await ImagePicker.launchImageLibraryAsync({
        mediaTypes: ["images"],
        quality: 0.8,
      });

      if (result.canceled || result.assets.length === 0) {
        return;
      }

      const asset = result.assets[0];

      await runScanPipeline({
        uri: asset.uri,
      });
    } catch (error) {
      const message =
        error instanceof Error
          ? error.message
          : "Unable to select a receipt image.";

      Alert.alert("Selection failed", message);
    } finally {
      setIsPicking(false);
    }
  }

  async function handleTakePhoto() {
    if (isBusy) {
      return;
    }

    setIsPicking(true);

    try {
      const permission = await ImagePicker.requestCameraPermissionsAsync();

      if (!permission.granted) {
        Alert.alert(
          "Permission required",
          "Allow camera access to scan a receipt.",
        );
        return;
      }

      const result = await ImagePicker.launchCameraAsync({
        mediaTypes: ["images"],
        quality: 0.8,
      });

      if (result.canceled || result.assets.length === 0) {
        return;
      }

      const asset = result.assets[0];

      await runScanPipeline({
        uri: asset.uri,
      });
    } catch (error) {
      const message =
        error instanceof Error
          ? error.message
          : "Unable to capture a receipt photo.";

      Alert.alert("Camera failed", message);
    } finally {
      setIsPicking(false);
    }
  }

  function handleRetryProcessing() {
    if (isBusy || !failedReceiptId) {
      return;
    }

    processMutation.mutate(failedReceiptId);
  }

  function handleStartOver() {
    if (isBusy) {
      return;
    }

    setSelectedImage(null);
    setFailedReceiptId(null);
  }

  return (
    <SafeAreaView>
      <ScrollView>
        <Text>Scan receipt</Text>

        <Text>
          Select a receipt image from your photo library or take a new
          photo. Detected merchant, amount, currency, and date can be
          corrected before the expense is created.
        </Text>

        {selectedImage ? (
          <Image
            source={{ uri: selectedImage.uri }}
            style={{ width: 160, height: 160 }}
            resizeMode="contain"
          />
        ) : null}

        {uploadMutation.isPending ? (
          <View>
            <ActivityIndicator />
            <Text>Uploading receipt...</Text>
          </View>
        ) : processMutation.isPending ? (
          <View>
            <ActivityIndicator />
            <Text>Reading receipt...</Text>
          </View>
        ) : failedReceiptId ? (
          <View>
            <Text>
              We could not read this receipt automatically.
            </Text>

            <Button title="Retry" onPress={handleRetryProcessing} />

            <Button
              title="Start over"
              onPress={handleStartOver}
            />
          </View>
        ) : (
          <View>
            <Button
              title="Choose from library"
              onPress={handlePickFromLibrary}
              disabled={isPicking}
            />

            <Button
              title="Take photo"
              onPress={handleTakePhoto}
              disabled={isPicking}
            />
          </View>
        )}
      </ScrollView>
    </SafeAreaView>
  );
}
