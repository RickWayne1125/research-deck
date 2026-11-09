// The background art of radix-ui.com's home page: BackgroundImage in app/(default)/page.client.tsx of
// https://github.com/radix-ui/website, as SVG markup (paths rounded to 0.1, ids suffixed -rd). Its gradients take
// their colors from --color-background-image-base and --color-background-image-accent-1…7, which the palette classes
// in styles/backdrop.css set (red, indigo, teal: the site's examples). Drawn by components/Backdrop.tsx.
//
// MIT License
//
// Copyright (c) 2024 WorkOS
//
// Permission is hereby granted, free of charge, to any person obtaining a copy of this software and associated
// documentation files (the "Software"), to deal in the Software without restriction, including without limitation the
// rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the Software, and to
// permit persons to whom the Software is furnished to do so, subject to the following conditions:
//
// The above copyright notice and this permission notice shall be included in all copies or substantial portions of the
// Software.
//
// THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE
// WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR
// COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR
// OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.

/** The art's viewBox (the site draws it max(2560px, 100vw) wide, centered at the top, at half opacity). */
export const RADIX_ART_VIEWBOX = '0 0 2560 1920';

export const RADIX_ART = `<g>
<path d="M3020.9 134.5C3124.8 173.8 3165 266.8 3110.7 342.1C2627.6 1011.9 1866.3 2517.6 1361.8 2752C-681.4 3429.2 -4156.8 2571.5 -2138.3 1425.4C-119.8 279.3 -1553.4 -218.3 -406.2 -990.9C930 -1890.8 2560.5 -40.1 3020.9 134.5Z" fill="url(#paint0_radial_37_453-rd)"></path>
<path d="M885.9 -99.2L1864.7 271.8C1921.1 293.2 1961.3 331.8 1974.2 377L2135.2 941.2L2866.2 715C2924.7 696.9 2991.4 698.8 3047.8 720.2L4026.6 1091.2C4130.5 1130.6 4170.7 1223.5 4116.4 1298.8L3855.8 1660.2C3833.1 1691.6 3796.1 1716.4 3751 1730.4L2473.2 2125.6L2754.3 3110.9C2764.4 3146.3 2757 3183.1 2733.4 3214.9L2367.5 3708.8L1209 3269.7C1152.6 3248.3 1112.4 3209.7 1099.5 3164.5C816.8 2173.9 718.6 2080.2 290.7 580.3C250.8 440.6 316.2 358.6 338.9 327.1L599.5 -34.2C653.8 -109.5 782 -138.6 885.9 -99.2Z" fill="url(#paint1_radial_37_453-rd)"></path>
<path d="M1597.1 169.8L2576 540.8C2632.4 562.2 2672.6 600.8 2685.5 646L2846.4 1210.2L3577.4 984C3636 965.9 3702.6 967.8 3759 989.2L4737.9 1360.2C4841.7 1399.6 4881.9 1492.5 4827.6 1567.8L4567 1929.2C4544.3 1960.6 4507.3 1985.4 4462.2 1999.4L3184.4 2394.6L3465.5 3379.9C3475.6 3415.3 3468.2 3452.1 3444.7 3483.9L3078.7 3977.8L1920.2 3538.7C1863.8 3517.3 1823.6 3478.7 1810.7 3433.5L1649.7 2869.3L918.8 3095.4C860.2 3113.5 793.5 3111.6 737.1 3090.3C737.1 3090.3 -278.9 2706.8 -70.7 2151.5C137.5 1596.2 725.3 1866.2 1311.8 1684.8L1030.4 698.6C1020.5 663.8 1027.4 627.6 1050.1 596.1L1310.7 234.8C1365 159.5 1493.3 130.4 1597.1 169.8Z" fill="url(#paint2_radial_37_453-rd)"></path>
<path d="M646.6 3987.9L-98.4 1153.8L4970.7 -538.6L8169.2 3987.9H646.6Z" fill="url(#paint3_radial_114_43-rd)"></path>
<path d="M793.7 3742.8L48.7 908.7L5117.7 -783.7L8316.2 3742.8H793.7Z" fill="url(#paint4_radial_114_43-rd)"></path>
<ellipse cx="2396.98" cy="275.232" rx="1699.15" ry="1558.77" fill="url(#paint5_radial_114_43-rd)"></ellipse>
<path opacity="0.5" d="M6290.2 3071.5L3745.5 4524.7L283 -523.6L4343.3 -4194.7L6290.2 3071.5Z" fill="url(#paint6_radial_114_43-rd)"></path>
<path d="M3059.3 767.9C3338.1 1712.5 3585.8 2551.4 3864.6 3496C3891.2 3586.2 3837.4 3707 3744.4 3765.7C2803.8 4359.7 -787.9 5319.2 63.3 2765.5C176.8 2425.2 313.7 2187.1 594.3 2175.2C874.9 2163.4 1279.8 2345.4 1646.7 2313.3C2175.9 2267 2044.1 1215.1 2396.1 992.9L2842.6 711C2935.6 652.2 3032.6 677.7 3059.3 767.9Z" fill="url(#paint4_radial_37_453-rd)"></path>
</g>
<defs>
<radialGradient id="paint3_radial_114_43-rd" cx="0" cy="0" r="1" gradientUnits="userSpaceOnUse" gradientTransform="translate(2922 2538.48) rotate(-117.986) scale(1898.15 3571.73)">
<stop style="stop-color: var(--color-background-image-base);"></stop>
<stop offset="0.822917" style="stop-color: var(--color-background-image-base);"></stop>
<stop offset="1" style="stop-color: var(--color-background-image-base); stop-opacity: 0;"></stop>
</radialGradient>
<radialGradient id="paint4_radial_114_43-rd" cx="0" cy="0" r="1" gradientUnits="userSpaceOnUse" gradientTransform="translate(3069.05 2293.39) rotate(-117.986) scale(1898.15 3571.73)">
<stop style="stop-color: var(--color-background-image-base);"></stop>
<stop offset="0.822917" style="stop-color: var(--color-background-image-base);"></stop>
<stop offset="1" style="stop-color: var(--color-background-image-base); stop-opacity: 0;"></stop>
</radialGradient>
<radialGradient id="paint5_radial_114_43-rd" cx="0" cy="0" r="1" gradientUnits="userSpaceOnUse" gradientTransform="translate(2994.87 275.232) rotate(118.839) scale(1779.46 2065.6)">
<stop offset="0.328125" style="stop-color: var(--color-background-image-accent-1); stop-opacity: 1;"></stop>
<stop offset="1" style="stop-color: white; stop-opacity: 0;"></stop>
</radialGradient>
<radialGradient id="paint6_radial_114_43-rd" cx="0" cy="0" r="1" gradientUnits="userSpaceOnUse" gradientTransform="translate(3934.59 656.035) rotate(148.98) scale(1938.73 3648.08)">
<stop style="stop-color: var(--color-background-image-base);"></stop>
<stop offset="0.789375" style="stop-color: var(--color-background-image-base);"></stop>
<stop offset="1" style="stop-color: var(--color-background-image-base); stop-opacity: 0;"></stop>
</radialGradient>
<radialGradient id="paint0_radial_37_453-rd" cx="0" cy="0" r="1" gradientUnits="userSpaceOnUse" gradientTransform="translate(-804.109 -2036.8) rotate(64.9401) scale(6436.87 6304.81)">
<stop style="stop-color: var(--color-background-image-base);"></stop>
<stop offset="0.0833333" style="stop-color: var(--color-background-image-accent-1);"></stop>
<stop offset="0.364583" style="stop-color: var(--color-background-image-accent-2);"></stop>
<stop offset="0.658041" style="stop-color: var(--color-background-image-base);"></stop>
<stop offset="0.798521" style="stop-color: var(--color-background-image-accent-3);"></stop>
<stop offset="0.942708" style="stop-color: var(--color-background-image-base);"></stop>
<stop offset="1" style="stop-color: var(--color-background-image-base);"></stop>
</radialGradient>
<radialGradient id="paint1_radial_37_453-rd" cx="0" cy="0" r="1" gradientUnits="userSpaceOnUse" gradientTransform="translate(201.6 -1080.02) rotate(64.9401) scale(6436.87 6304.81)">
<stop style="stop-color: var(--color-background-image-base);"></stop>
<stop offset="0.0833333" style="stop-color: var(--color-background-image-accent-4);"></stop>
<stop offset="0.333803" style="stop-color: var(--color-background-image-accent-5);"></stop>
<stop offset="0.658041" style="stop-color: var(--color-background-image-base);"></stop>
<stop offset="0.798521" style="stop-color: var(--color-background-image-accent-3);"></stop>
<stop offset="0.942708" style="stop-color: var(--color-background-image-base);"></stop>
<stop offset="1" style="stop-color: var(--color-background-image-base);"></stop>
</radialGradient>
<radialGradient id="paint2_radial_37_453-rd" cx="0" cy="0" r="1" gradientUnits="userSpaceOnUse" gradientTransform="translate(912.834 -811.021) rotate(64.9401) scale(6436.87 6304.81)">
<stop style="stop-color: var(--color-background-image-base);"></stop>
<stop offset="0.140625" style="stop-color: var(--color-background-image-accent-6);"></stop>
<stop offset="0.333803" style="stop-color: var(--color-background-image-accent-7);"></stop>
<stop offset="0.658041" style="stop-color: var(--color-background-image-base);"></stop>
<stop offset="0.798521" style="stop-color: var(--color-background-image-accent-3);"></stop>
<stop offset="0.942708" style="stop-color: var(--color-background-image-base);"></stop>
<stop offset="1" style="stop-color: var(--color-background-image-base);"></stop>
</radialGradient>
<radialGradient id="paint3_radial_37_453-rd" cx="0" cy="0" r="1" gradientUnits="userSpaceOnUse" gradientTransform="translate(1711.41 -1639.11) rotate(64.9401) scale(6436.87 6304.81)">
<stop style="stop-color: var(--color-background-image-base);"></stop>
<stop offset="0.0833333" style="stop-color: var(--color-background-image-accent-1);"></stop>
<stop offset="0.333803" style="stop-color: var(--color-background-image-accent-5);"></stop>
<stop offset="0.658041" style="stop-color: var(--color-background-image-base);"></stop>
<stop offset="0.798521" style="stop-color: var(--color-background-image-accent-3);"></stop>
<stop offset="0.942708" style="stop-color: var(--color-background-image-base);"></stop>
<stop offset="1" style="stop-color: var(--color-background-image-base);"></stop>
</radialGradient>
<radialGradient id="paint4_radial_37_453-rd" cx="0" cy="0" r="1" gradientUnits="userSpaceOnUse" gradientTransform="translate(3479.06 -623.459) rotate(113.028) scale(8332.26 4870.62)">
<stop style="stop-color: var(--color-background-image-base);"></stop>
<stop offset="0.0833333" style="stop-color: var(--color-background-image-accent-1);"></stop>
<stop offset="0.333803" style="stop-color: var(--color-background-image-accent-5);"></stop>
<stop offset="0.658041" style="stop-color: var(--color-background-image-base);"></stop>
<stop offset="0.798521" style="stop-color: var(--color-background-image-accent-3);"></stop>
<stop offset="0.942708" style="stop-color: var(--color-background-image-base);"></stop>
<stop offset="1" style="stop-color: var(--color-background-image-base);"></stop>
</radialGradient>
</defs>`;
