// HARNESS: our code (MIT), not part of the port.
// Runs the Java port's built-property calculator on the case's input and writes its results in the
// COBOL's own output layout, so Tare weighs both sides with one layout.
//   input/bills.dat   600-byte bills (copybook XCOMBAT), the records the COBOL harness passes to CTXTA3B
//   input/rates.dat   200-byte rate records, the lines harness/LOADTAU loads into the rate file
//   out/retours.dat   600-byte return records (copybook XRETB); CR and RC in the last 4 bytes, as TFBATCH
// The rates go to the port in its own JSON rate format (RateLoader). Every amount in the output is the
// port's. The bill's identity block (year, direction, commune, owner, IFP) is copied from the input: the
// port keeps the commune code as an integer and does not carry the owner fields.
// A bill the port throws on is left out of the output (it weighs as a missing record) and logged.
// Usage: java -cp <port jar>:<classes> TareJavaSide <input dir> <out dir> <scratch dir>
import fr.dgfip.taxefonciere.calculator.BuiltPropertyCalculator;
import fr.dgfip.taxefonciere.model.input.Combat;
import fr.dgfip.taxefonciere.model.output.RetourB;
import fr.dgfip.taxefonciere.rate.ErrorCode;
import fr.dgfip.taxefonciere.rate.RateLoader;

import java.io.OutputStream;
import java.math.BigDecimal;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;

public class TareJavaSide {
    static final int BILL = 600, RATE = 200, OUT = 600;
    // rates.dat columns 5..18, as the port's TaxRate names them
    static final String[] RATE_NAMES = {"taudepb", "ptbtas", "taucomb", "ptbsyn", "ptbcu", "tautseb", "ptbtgp",
        "ptbgem", "pbbomp", "pbboma", "pbbomb", "pbbomc", "pbbomd", "pbbome"};

    /** A PIC S9(n) DISPLAY field: digits, the sign in the last digit ('p'-'y' negative); blank is null. */
    static BigDecimal s9(String rec, int off, int len) {
        String raw = rec.substring(off, off + len);
        if (raw.isBlank()) return null;
        char last = raw.charAt(len - 1);
        boolean neg = last >= 'p' && last <= 'y';
        String digits = neg ? raw.substring(0, len - 1) + (char) ('0' + (last - 'p')) : raw;
        BigDecimal v = new BigDecimal(digits.trim());
        return neg ? v.negate() : v;
    }

    static void put(char[] out, int off, String s) {
        for (int i = 0; i < s.length(); i++) out[off + i] = s.charAt(i);
    }

    /** A whole-euro amount as PIC S9(len) DISPLAY; a fraction is a hard error, never rounded here. */
    static void num(char[] out, int off, int len, BigDecimal v, String where) {
        if (v == null) v = BigDecimal.ZERO;
        BigDecimal w = v.stripTrailingZeros();
        if (w.scale() > 0) throw new IllegalStateException(where + ": the port returned a fraction " + v.toPlainString());
        String digits = w.abs().toBigIntegerExact().toString();
        if (digits.length() > len) throw new IllegalStateException(where + ": " + v + " does not fit in " + len + " digits");
        digits = "0".repeat(len - digits.length()) + digits;
        if (v.signum() < 0) digits = digits.substring(0, len - 1) + (char) ('p' + (digits.charAt(len - 1) - '0'));
        put(out, off, digits);
    }

    static BigDecimal at(BigDecimal[] a, int i) { return a == null ? null : a[i]; }

    public static void main(String[] args) throws Exception {
        Path in = Paths.get(args[0]), outDir = Paths.get(args[1]), scratch = Paths.get(args[2]);
        Files.createDirectories(outDir);
        Files.createDirectories(scratch);

        String rates = new String(Files.readAllBytes(in.resolve("rates.dat")), StandardCharsets.ISO_8859_1);
        StringBuilder js = new StringBuilder("[");
        for (int r = 0; r < rates.length(); r += RATE) {
            String[] t = rates.substring(r, r + RATE).trim().split(";", -1);
            js.append(r == 0 ? "" : ",").append("{\"jan\":2018,\"depdir\":\"").append(t[0])
              .append("\",\"ccocom\":").append(Integer.parseInt(t[1]))
              .append(",\"ccoifp\":\"").append(t[2]).append("\",\"ccpper\":\"").append(t[3]).append('"');
            for (int i = 0; i < RATE_NAMES.length; i++) js.append(",\"").append(RATE_NAMES[i]).append("\":").append(t[4 + i]);
            js.append('}');
        }
        Path json = scratch.resolve("rates.json");
        Files.write(json, js.append(']').toString().getBytes(StandardCharsets.UTF_8));
        RateLoader loader = new RateLoader();
        loader.loadRates(json.toString());

        String bills = new String(Files.readAllBytes(in.resolve("bills.dat")), StandardCharsets.ISO_8859_1);
        int n = 0, failed = 0;
        try (OutputStream os = Files.newOutputStream(outDir.resolve("retours.dat"))) {
            for (int b = 0; b < bills.length(); b += BILL) {
                String rec = bills.substring(b, b + BILL);
                String key = rec.substring(5, 11);
                n++;
                try {
                    Combat c = new Combat();
                    c.setCcobnb(rec.substring(0, 1));
                    c.setDan(rec.substring(1, 5));
                    c.setAc3dir(rec.substring(5, 8));
                    c.setCcocom(rec.substring(8, 11));
                    c.setDsrpar(rec.substring(11, 12));
                    c.setCgroup(rec.substring(12, 13));
                    c.setNnupro(Integer.parseInt(rec.substring(13, 18)));
                    c.setMbacom(s9(rec, 26, 10));
                    c.setMbadep(s9(rec, 36, 10));
                    c.setMbareg(s9(rec, 46, 10));
                    c.setMbasyn(s9(rec, 56, 10));
                    c.setMbacu(s9(rec, 66, 10));
                    c.setMbatse(s9(rec, 76, 10));
                    c.setMbbt13(new BigDecimal[]{s9(rec, 86, 10), s9(rec, 96, 10)});
                    String[] gt = new String[6];
                    BigDecimal[] mb = new BigDecimal[6];
                    for (int i = 0; i < 6; i++) {
                        gt[i] = rec.substring(126 + 12 * i, 128 + 12 * i);
                        mb[i] = s9(rec, 128 + 12 * i, 10);
                    }
                    c.setGtauom(gt);
                    c.setMbaom(mb);
                    c.setMvltim(s9(rec, 318, 10));
                    c.setMbage3(s9(rec, 344, 10));
                    c.setMbata3(s9(rec, 354, 10));
                    c.setCcoifp(rec.substring(364, 367));
                    c.setCcpper(rec.substring(367, 370));

                    BuiltPropertyCalculator.Resultat res = new BuiltPropertyCalculator(loader).calculer(c);
                    ErrorCode ec = res.getErrorCode();
                    RetourB r = res.getRetourB() != null ? res.getRetourB() : new RetourB();

                    char[] o = new char[OUT];
                    java.util.Arrays.fill(o, ' ');
                    put(o, 0, rec.substring(1, 12));     // DAN, AC3DIR, CCOCOM, DSRPAR
                    put(o, 11, rec.substring(12, 18));   // CGROUP, NNUPRO
                    put(o, 17, rec.substring(0, 1));     // CCOBNB
                    num(o, 18, 10, r.getMctcom(), key + " mctcom");
                    num(o, 28, 10, r.getMctdep(), key + " mctdep");
                    num(o, 38, 10, r.getMctreg(), key + " mctreg");
                    num(o, 48, 10, r.getMctsyn(), key + " mctsyn");
                    num(o, 58, 10, r.getMctcu(), key + " mctcu");
                    num(o, 68, 10, r.getMcttse(), key + " mcttse");
                    num(o, 78, 10, at(r.getMcibt13(), 0), key + " mcbt13_1");
                    num(o, 88, 10, at(r.getMcibt13(), 1), key + " mcbt13_2");
                    num(o, 98, 10, r.getMcbtsa(), key + " mcbtsa");
                    for (int i = 0; i < 6; i++) {
                        String g = r.getGtauom() == null || r.getGtauom()[i] == null ? "  " : r.getGtauom()[i];
                        put(o, 148 + 12 * i, (g + "  ").substring(0, 2));
                        num(o, 150 + 12 * i, 10, at(r.getMctom(), i), key + " mctom" + (i + 1));
                    }
                    num(o, 220, 10, r.getMfa300(), key + " mfa300");
                    num(o, 230, 10, r.getMfn300(), key + " mfn300");
                    num(o, 240, 10, r.getMfa800(), key + " mfa800");
                    num(o, 250, 10, r.getMfn800(), key + " mfn800");
                    num(o, 260, 12, r.getTcthfr(), key + " tcthfr");
                    num(o, 272, 12, r.getTctfra(), key + " tctfra");
                    num(o, 284, 12, r.getTctdu(), key + " tctdu");
                    num(o, 296, 10, r.getMfa900(), key + " mfa900");
                    num(o, 306, 10, r.getMfn900(), key + " mfn900");
                    num(o, 316, 10, r.getTctom(), key + " tctom");
                    num(o, 326, 10, r.getMvltim(), key + " mvltim");
                    num(o, 336, 10, r.getMcoge3(), key + " mcoge3");
                    num(o, 346, 10, r.getMcota3(), key + " mcota3");
                    put(o, 356, rec.substring(364, 370));   // CCOIFP, CCPPER
                    put(o, 596, String.format("%02d%02d", ec.getCr(), ec.getRc()));
                    os.write(new String(o).getBytes(StandardCharsets.ISO_8859_1));
                } catch (RuntimeException e) {
                    failed++;
                    System.err.println("bill " + key + ": the port threw " + e);
                }
            }
        }
        System.out.println("TareJavaSide: bills " + n + ", left out after an exception " + failed);
    }
}
