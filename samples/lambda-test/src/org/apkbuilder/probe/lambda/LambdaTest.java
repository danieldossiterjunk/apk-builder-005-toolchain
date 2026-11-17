package org.apkbuilder.probe.lambda;

import java.util.ArrayList;
import java.util.Arrays;
import java.util.Comparator;
import java.util.List;
import java.util.function.Function;
import java.util.function.IntBinaryOperator;
import java.util.function.Supplier;
import java.util.stream.Collectors;

/**
 * Stage 0/1 sample for D8 desugaring: Java 8 language features that D8 must rewrite for ART
 * (lambdas, capturing lambdas, method references, default and static interface methods,
 * try-with-resources with suppressed exceptions) plus java.util.stream. run() returns one line
 * of text; the same text on the desktop JVM and on ART shows the converted code behaves the same.
 */
public final class LambdaTest {
    private LambdaTest() {}

    interface Shape {
        double area();
        default String describe() { return name() + "=" + Math.round(area() * 100) / 100.0; }
        String name();
        static Shape square(final double s) {
            return new Shape() {
                @Override public double area() { return s * s; }
                @Override public String name() { return "square"; }
            };
        }
    }

    static final class Res implements AutoCloseable {
        private final List<String> log;
        private final String id;
        Res(List<String> log, String id) { this.log = log; this.id = id; log.add("open " + id); }
        @Override public void close() { log.add("close " + id); throw new IllegalStateException("close " + id); }
    }

    public static String run() {
        final int base = 7;
        IntBinaryOperator add = (a, b) -> a + b + base;                  // capturing lambda
        Function<String, Integer> len = String::length;                   // method reference
        Supplier<List<String>> mk = ArrayList::new;                       // constructor reference
        List<String> words = mk.get();
        words.addAll(Arrays.asList("delta", "alpha", "charlie", "bravo"));
        words.sort(Comparator.comparing(len).thenComparing(Comparator.reverseOrder()));
        String joined = words.stream().map(w -> w.toUpperCase()).collect(Collectors.joining(","));
        Shape sq = Shape.square(1.5);
        List<String> log = new ArrayList<>();
        String suppressed = "";
        try (Res r1 = new Res(log, "a"); Res r2 = new Res(log, "b")) {
            log.add("body");
            throw new RuntimeException("body");
        } catch (RuntimeException e) {
            StringBuilder sb = new StringBuilder(e.getMessage());
            for (Throwable s : e.getSuppressed()) sb.append('+').append(s.getMessage());
            suppressed = sb.toString();
        }
        return "add=" + add.applyAsInt(2, 3) + " sorted=" + joined + " " + sq.describe() + " log=" + log + " ex=" + suppressed;
    }

    public static void main(String[] args) {
        System.out.println(run());
    }
}
