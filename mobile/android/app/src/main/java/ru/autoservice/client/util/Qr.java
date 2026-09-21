package ru.autoservice.client.util;

import android.graphics.Bitmap;
import android.graphics.Color;

import androidx.annotation.ColorInt;
import androidx.annotation.NonNull;
import androidx.annotation.Nullable;

import com.google.zxing.BarcodeFormat;
import com.google.zxing.EncodeHintType;
import com.google.zxing.WriterException;
import com.google.zxing.common.BitMatrix;
import com.google.zxing.qrcode.QRCodeWriter;
import com.google.zxing.qrcode.decoder.ErrorCorrectionLevel;

import java.util.EnumMap;
import java.util.Map;

/**
 * QR-код ссылки-приглашения.
 *
 * <p>Единственное место, где используется zxing. Рисуем битмап сами, без
 * android-обвязки библиотеки: нам нужна только матрица, а камера и вовсе
 * не нужна.
 */
public final class Qr {

    /**
     * Запас на повреждения — средний. Код показывают с экрана телефона:
     * бликов и пальцев на нём хватает, а до «высокого» уровня платить
     * плотностью модулей уже незачем.
     */
    private static final ErrorCorrectionLevel CORRECTION = ErrorCorrectionLevel.M;

    /**
     * Поле вокруг кода в модулях. Стандарт требует четыре: без него
     * сканеры не находят границу кода на светлом экране.
     */
    private static final int QUIET_ZONE = 2;

    private Qr() {
    }

    /**
     * Битмап с кодом или null, если закодировать не удалось.
     *
     * <p>Null вместо исключения намеренно: отсутствие картинки не повод
     * ронять экран — рядом всегда есть сам код текстом и кнопка
     * «Поделиться».
     */
    @Nullable
    public static Bitmap encode(@NonNull String value, int sizePx,
                                @ColorInt int foreground, @ColorInt int background) {
        if (value.isEmpty() || sizePx <= 0) {
            return null;
        }

        Map<EncodeHintType, Object> hints = new EnumMap<>(EncodeHintType.class);
        hints.put(EncodeHintType.ERROR_CORRECTION, CORRECTION);
        hints.put(EncodeHintType.MARGIN, QUIET_ZONE);
        // Ссылка латиницей, но кодировку задаём явно: иначе на части
        // устройств zxing возьмёт системную и код прочитается мусором.
        hints.put(EncodeHintType.CHARACTER_SET, "UTF-8");

        BitMatrix matrix;
        try {
            matrix = new QRCodeWriter().encode(value, BarcodeFormat.QR_CODE, sizePx, sizePx, hints);
        } catch (WriterException | IllegalArgumentException e) {
            return null;
        }

        int width = matrix.getWidth();
        int height = matrix.getHeight();
        int[] pixels = new int[width * height];
        for (int y = 0; y < height; y++) {
            int offset = y * width;
            for (int x = 0; x < width; x++) {
                pixels[offset + x] = matrix.get(x, y) ? foreground : background;
            }
        }

        Bitmap bitmap = Bitmap.createBitmap(width, height, Bitmap.Config.ARGB_8888);
        bitmap.setPixels(pixels, 0, width, 0, 0, width, height);
        return bitmap;
    }

    /** Код чёрным по белому: так его читают все сканеры, включая старые. */
    @Nullable
    public static Bitmap encode(@NonNull String value, int sizePx) {
        return encode(value, sizePx, Color.BLACK, Color.WHITE);
    }
}
