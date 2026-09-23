package ru.autoservice.client.ui.common;

import android.content.Context;
import android.graphics.Bitmap;
import android.graphics.BlurMaskFilter;
import android.graphics.Canvas;
import android.graphics.LinearGradient;
import android.graphics.Paint;
import android.graphics.PorterDuff;
import android.graphics.PorterDuffColorFilter;
import android.graphics.Shader;
import android.graphics.drawable.Drawable;
import android.util.AttributeSet;
import android.view.View;

import androidx.annotation.NonNull;
import androidx.annotation.Nullable;
import androidx.core.content.ContextCompat;

import java.util.Locale;

import ru.autoservice.client.R;

/**
 * Фирменный знак: силуэт машины неоновой трубкой и «хромированная»
 * надпись под линией борта.
 *
 * <p>Своя View, а не картинка и не пара ImageView с TextView, потому что
 * знак состоит из двух эффектов, которых в Android нет готовых. Свечение
 * на сайте даёт CSS-фильтр `drop-shadow` в три слоя; здесь оно собирается
 * из размытых альфа-копий силуэта. «Хром» на сайте — градиент,
 * подрезанный по тексту (`background-clip: text`); здесь это
 * {@link LinearGradient} в качестве шейдера у текстовой кисти.
 *
 * <p>Пропорции и посадка надписи повторяют landing.css один в один и
 * считаются от ШИРИНЫ, а не от высоты: высота зависит от пропорций
 * рисунка, и при его замене проценты поехали бы. Надпись стоит под линией
 * кузова, а не поперёк неё — на прежней посадке длинная линия борта
 * проходила ровно по верхушкам букв.
 *
 * <p>Рисование идёт в программном слое: {@link BlurMaskFilter} на GPU не
 * поддерживается, и без этого размытие просто не появится.
 */
public class BrandMarkView extends View {

    /** Пропорции рисунка: 1483 × 326 в его собственных единицах. */
    private static final float ASPECT = 326f / 1483f;

    /** Отступ надписи сверху и её кегль — доли ширины знака, как в CSS. */
    private static final float WORD_TOP = 0.137f;
    private static final float WORD_SIZE = 0.078f;

    /**
     * Наклон вместо курсива: у жирных гротесков настоящего курсива нет, а
     * синтетический системы рисуют по-разному. −9° это tan(9°) ≈ 0.158.
     */
    private static final float WORD_SKEW = -0.158f;

    /**
     * На образце гарнитура заметно шире стандартной. На сайте растяжения
     * хватает 1.1, потому что там за основу берётся Arial Black; системный
     * Roboto Black заметно уже, и без добавки надпись выходит короче, чем
     * на витрине.
     */
    private static final float WORD_STRETCH = 1.18f;

    /**
     * Слои свечения: радиус размытия в долях ширины, цвет и прозрачность.
     * Три слоя повторяют то, как светится настоящая трубка — почти белая
     * сердцевина, синий ореол, дальнее тёмно-синее зарево.
     */
    private static final float[] GLOW_RADIUS = {0.009f, 0.03f, 0.075f};
    private static final int[] GLOW_ALPHA = {255, 200, 130};

    /**
     * «Хром»: светлый верх, тёмная полоса-горизонт по центру, отблеск
     * снизу. Стопы взяты из landing.css без изменений.
     */
    private static final int[] CHROME_COLORS = {
            0xFFFFFFFF, 0xFFEAF6FF, 0xFFA6D4F7, 0xFF4C88BD,
            0xFFD7EDFF, 0xFFFFFFFF, 0xFFA9CFEC,
    };
    private static final float[] CHROME_STOPS = {
            0.02f, 0.20f, 0.40f, 0.50f, 0.60f, 0.78f, 1.00f,
    };

    private final Paint carPaint = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final Paint glowPaint = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final Paint wordPaint = new Paint(Paint.ANTI_ALIAS_FLAG);

    private Drawable car;
    private String word = "";

    @Nullable private Bitmap carBitmap;
    /** Размытые альфа-копии силуэта и их смещения — считаются один раз. */
    @Nullable private Bitmap[] glow;
    @Nullable private int[][] glowOffset;

    public BrandMarkView(Context context) {
        this(context, null);
    }

    public BrandMarkView(Context context, @Nullable AttributeSet attrs) {
        super(context, attrs);
        init(context);
    }

    private void init(@NonNull Context context) {
        car = ContextCompat.getDrawable(context, R.drawable.ic_logo_mark);
        word = context.getString(R.string.app_name).toUpperCase(new Locale("ru"));

        wordPaint.setTypeface(android.graphics.Typeface.create(
                "sans-serif-black", android.graphics.Typeface.NORMAL));
        wordPaint.setTextAlign(Paint.Align.CENTER);
        wordPaint.setTextSkewX(WORD_SKEW);
        wordPaint.setTextScaleX(WORD_STRETCH);

        // BlurMaskFilter аппаратным слоем не рисуется — без этого свечения
        // просто не будет, и ошибки при этом никакой не возникнет.
        setLayerType(LAYER_TYPE_SOFTWARE, null);
    }

    @Override
    protected void onMeasure(int widthMeasureSpec, int heightMeasureSpec) {
        int width = resolveSize(getSuggestedMinimumWidth(), widthMeasureSpec);
        // Высота всегда следует за шириной: знак — картинка с фиксированными
        // пропорциями, растянуть его по вертикали значит испортить.
        setMeasuredDimension(width, Math.round(width * ASPECT));
    }

    @Override
    protected void onSizeChanged(int width, int height, int oldWidth, int oldHeight) {
        super.onSizeChanged(width, height, oldWidth, oldHeight);
        rebuild(width, height);
    }

    private void rebuild(int width, int height) {
        recycle();
        if (width <= 0 || height <= 0 || car == null) {
            return;
        }

        try {
            Bitmap source = Bitmap.createBitmap(width, height, Bitmap.Config.ARGB_8888);
            Canvas canvas = new Canvas(source);
            car.setBounds(0, 0, width, height);
            car.draw(canvas);
            carBitmap = source;

            glow = new Bitmap[GLOW_RADIUS.length];
            glowOffset = new int[GLOW_RADIUS.length][];
            Paint blur = new Paint();
            for (int i = 0; i < GLOW_RADIUS.length; i++) {
                float radius = Math.max(GLOW_RADIUS[i] * width, 1f);
                blur.setMaskFilter(new BlurMaskFilter(radius, BlurMaskFilter.Blur.NORMAL));
                int[] offset = new int[2];
                // extractAlpha даёт готовую размытую маску силуэта: сам
                // рисунок при этом не копируется, только его альфа.
                glow[i] = source.extractAlpha(blur, offset);
                glowOffset[i] = offset;
            }
        } catch (OutOfMemoryError error) {
            // Знак — украшение, а не механизм: на нехватке памяти
            // отказываемся от свечения и рисуем силуэт как есть.
            recycle();
        }
    }

    @Override
    protected void onDetachedFromWindow() {
        recycle();
        super.onDetachedFromWindow();
    }

    private void recycle() {
        carBitmap = null;
        glow = null;
        glowOffset = null;
    }

    @Override
    protected void onDraw(@NonNull Canvas canvas) {
        int width = getWidth();
        if (width <= 0) {
            return;
        }

        drawCar(canvas, width);
        drawWord(canvas, width);
    }

    private void drawCar(@NonNull Canvas canvas, int width) {
        if (carBitmap == null || glow == null || glowOffset == null) {
            if (car != null) {
                car.setBounds(0, 0, width, getHeight());
                car.draw(canvas);
            }
            return;
        }

        int[] colors = {
                ContextCompat.getColor(getContext(), R.color.neon_hot),
                ContextCompat.getColor(getContext(), R.color.neon),
                ContextCompat.getColor(getContext(), R.color.neon_deep),
        };
        // Снизу вверх: сначала дальнее зарево, последней — сердцевина.
        for (int i = glow.length - 1; i >= 0; i--) {
            glowPaint.setColorFilter(
                    new PorterDuffColorFilter(colors[i], PorterDuff.Mode.SRC_IN));
            glowPaint.setAlpha(GLOW_ALPHA[i]);
            canvas.drawBitmap(glow[i], glowOffset[i][0], glowOffset[i][1], glowPaint);
        }

        canvas.drawBitmap(carBitmap, 0, 0, carPaint);
    }

    private void drawWord(@NonNull Canvas canvas, int width) {
        if (word.isEmpty()) {
            return;
        }

        float size = width * WORD_SIZE;
        wordPaint.setTextSize(size);

        float top = width * WORD_TOP;
        Paint.FontMetrics metrics = wordPaint.getFontMetrics();
        float baseline = top - metrics.ascent;

        wordPaint.setShader(new LinearGradient(
                0, top, 0, top + size, CHROME_COLORS, CHROME_STOPS, Shader.TileMode.CLAMP));
        // Синий ореол под буквами: на сайте его даёт тот же drop-shadow,
        // что и у силуэта.
        wordPaint.setShadowLayer(
                size * 0.28f, 0, 0,
                ContextCompat.getColor(getContext(), R.color.neon));

        canvas.drawText(word, width / 2f, baseline, wordPaint);
    }
}
