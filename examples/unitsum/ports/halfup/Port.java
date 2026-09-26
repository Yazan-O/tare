// TEST FIXTURE for Tare's self-test: a Java port of mainframe/cbl/UNITSUM.cbl that rounds the pounds half-up (a deliberate difference).
// java -cp <classes> Port --input <dir> --out <dir>
// Reads <input>/items.dat (20-byte records) and writes <out>/totals.dat (40-byte records, by id).
import java.io.ByteArrayOutputStream;
import java.math.BigDecimal;
import java.math.RoundingMode;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.Map;
import java.util.TreeMap;

public class Port {
    static final BigDecimal LB_PER_KG = new BigDecimal("2.20462");

    static final class Total {
        int count;
        long qty;
        BigDecimal kg = BigDecimal.ZERO.setScale(3);
    }

    public static void main(String[] args) throws Exception {
        String input = null, out = null;
        for (int i = 0; i < args.length - 1; i++) {
            if (args[i].equals("--input")) input = args[i + 1];
            if (args[i].equals("--out")) out = args[i + 1];
        }
        byte[] data = Files.readAllBytes(Paths.get(input, "items.dat"));
        if (data.length % 20 != 0) throw new IllegalStateException("items.dat is not 20-byte records");
        Map<String, Total> totals = new TreeMap<>();
        for (int off = 0; off < data.length; off += 20) {
            String rec = new String(data, off, 20, StandardCharsets.ISO_8859_1);
            String id = rec.substring(0, 6);
            long qty = Long.parseLong(rec.substring(6, 11));
            BigDecimal unitKg = new BigDecimal(rec.substring(11, 18)).movePointLeft(3);
            Total t = totals.computeIfAbsent(id, k -> new Total());
            t.count += 1;
            t.qty += qty;
            t.kg = t.kg.add(unitKg.multiply(BigDecimal.valueOf(qty)));
        }
        ByteArrayOutputStream buf = new ByteArrayOutputStream();
        for (Map.Entry<String, Total> e : totals.entrySet()) {
            Total t = e.getValue();
            BigDecimal kg = t.kg.setScale(3);
            BigDecimal lb = kg.multiply(LB_PER_KG).setScale(2, RoundingMode.HALF_UP);
            String rec = e.getKey()
                    + digits(BigDecimal.valueOf(t.count), 3)
                    + digits(BigDecimal.valueOf(t.qty), 7)
                    + digits(kg.movePointRight(3), 11)
                    + overpunch(lb.movePointRight(2), 10)
                    + "   ";
            buf.write(rec.getBytes(StandardCharsets.ISO_8859_1));
        }
        Path dir = Paths.get(out);
        Files.createDirectories(dir);
        Files.write(dir.resolve("totals.dat"), buf.toByteArray());
    }

    static String digits(BigDecimal units, int width) {
        String s = units.abs().toBigInteger().toString();
        if (s.length() > width) throw new IllegalStateException(units + " does not fit " + width + " digits");
        return "0".repeat(width - s.length()) + s;
    }

    // Trailing overpunch as GnuCOBOL writes it with -fsign=EBCDIC: '{', 'A'-'I' positive; '}', 'J'-'R' negative.
    static String overpunch(BigDecimal units, int width) {
        String s = digits(units, width);
        int last = s.charAt(width - 1) - '0';
        char z = units.signum() < 0 ? "}JKLMNOPQR".charAt(last) : "{ABCDEFGHI".charAt(last);
        return s.substring(0, width - 1) + z;
    }
}
